"""Integrity-spine + crash-resume coverage (M5 exit criteria, 04 §7–8, NFR-2/3).

Every test here simulates an interruption — a yanked device mid-copy, a worker
that dies mid-job, a failed transcode, a corrupted copy — and then asserts two
things: nothing was lost or duplicated, and the *next* run completes normally.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from loomis.core import db, repository
from loomis.core.config import (
    BackupSettings,
    CoreSettings,
    DiarizeSettings,
    LlmSettings,
    Settings,
    SpeakerIdSettings,
    SttSettings,
    SummariesSettings,
)
from loomis.core.models import JobType, TranscodePolicy
from loomis.core.storage import sha256_file
from loomis.ingest import backup
from loomis.pipeline import steps as pipeline
from loomis.pipeline.runner import JobRunner
from loomis.scheduler import Scheduler

_AUDIO = b"RIFF\x00\x00\x00\x00WAVEfmt fake-audio-bytes-for-testing" * 16


def _settings(
    tmp_path: Path, *, policy: TranscodePolicy = TranscodePolicy.KEEP_ORIGINAL
) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        backup=BackupSettings(folder_settle_seconds=0.0, transcode_policy=policy),
        stt=SttSettings(engine="null"),
        diarize=DiarizeSettings(engine="null"),
        speaker_id=SpeakerIdSettings(engine="null"),
        llm=LlmSettings(provider="null"),
        summaries=SummariesSettings(diary_day_settle_minutes=0),
    )


def _conn(settings: Settings) -> sqlite3.Connection:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    c = db.connect(data_dir / "loomis.db")
    db.apply_migrations(c)
    return c


def _volume(tmp_path: Path, files: int = 1) -> Path:
    vol = tmp_path / "REC"
    vol.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (vol / f"clip{i}.wav").write_bytes(_AUDIO + bytes([i]))
    return vol


# --- backup interruption (FR-2.6: resume cleanly, never commit partials) ---


def test_midcopy_disconnect_then_reconnect_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A device yanked mid-copy loses nothing; the next connect imports normally."""
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path, files=2)
    device = backup.register_or_load_device(conn, vol, settings)

    real_copy2 = shutil.copy2
    copied = {"n": 0}

    def yanked(src: Path, dst: Path) -> Path:
        copied["n"] += 1
        if copied["n"] == 2:  # second file: simulate the device disappearing mid-copy
            Path(dst).write_bytes(b"partial")
            raise OSError("device disconnected")
        return Path(real_copy2(src, dst))

    monkeypatch.setattr(shutil, "copy2", yanked)
    report = backup.run_backup(conn, device, vol, settings)
    assert report.imported == 1
    assert report.errors == 1
    # Exactly the completed file is in the ledger; the partial never entered it.
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 1
    # Both sources are intact on the device.
    assert len(list(vol.glob("*.wav"))) == 2

    # Reconnect: the partial staging debris is swept and the missed file imports.
    monkeypatch.setattr(shutil, "copy2", real_copy2)
    report = backup.run_backup(conn, device, vol, settings)
    assert report.imported == 1
    assert report.errors == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 2
    staging = settings.core.resolved_data_dir / "staging"
    assert list(staging.iterdir()) == []  # nothing left in flight


def test_corrupt_directory_entry_skips_file_not_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A FAT-corrupted entry (WinError 1392) costs one error, not the whole import."""
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path, files=2)
    device = backup.register_or_load_device(conn, vol, settings)

    real_is_file = Path.is_file
    real_stat = Path.stat

    def flaky_is_file(self: Path) -> bool:
        if self.name == "clip1.wav":
            raise OSError(1392, "file or directory is corrupted and unreadable")
        return real_is_file(self)

    def flaky_stat(self: Path, *, follow_symlinks: bool = True) -> object:
        if self.name == "clip1.wav":
            raise OSError(1392, "file or directory is corrupted and unreadable")
        return real_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "is_file", flaky_is_file)
    monkeypatch.setattr(Path, "stat", flaky_stat)

    report = backup.run_backup(conn, device, vol, settings)
    assert report.imported == 1  # the healthy file made it
    assert report.errors == 1  # the corrupt one is counted, not fatal
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 1
    assert (vol / "clip1.wav").name in {p.name for p in vol.glob("*.wav")}  # source untouched


def test_quarantined_file_imports_after_corruption_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy that failed verification is retried (and succeeds) on the next run."""
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings)

    real_hash = sha256_file
    flaky = {"on": True}

    def corrupting_hash(path: Path) -> str:
        if flaky["on"] and "staging" in str(path):
            return "corrupted-copy-hash"
        return real_hash(path)

    monkeypatch.setattr(backup, "sha256_file", corrupting_hash)
    report = backup.run_backup(conn, device, vol, settings)
    assert report.quarantined == 1
    assert (vol / "clip0.wav").exists()  # source never deleted (FR-2.7)
    assert conn.execute("SELECT COUNT(*) AS n FROM quarantine").fetchone()["n"] == 1

    flaky["on"] = False  # cable reseated / disk healthy again
    report = backup.run_backup(conn, device, vol, settings)
    assert report.imported == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 1


# --- worker crash + reclaim (04 §7: a crashed worker's job is rerun, not lost) ---


def test_crashed_stt_job_reclaims_and_completes_once(tmp_path: Path) -> None:
    """Claim → crash → lease expiry → reclaim → exactly one transcript, day completes."""
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)

    # Worker 1 claims the stt job and dies (no complete/fail ever recorded).
    crashed = repository.claim_job(conn, "worker-crashed", lease_seconds=600, types=(JobType.STT,))
    assert crashed is not None
    # Its lease expires (backdate the claim past the lease window).
    conn.execute(
        "UPDATE jobs SET updated_at = datetime('now', '-3600 seconds') WHERE id = ?",
        (crashed.id,),
    )

    # A fresh runner reclaims and finishes the pipeline.
    assert JobRunner(settings).drain(conn) == 4  # stt → diarize → speaker_id → classify
    assert conn.execute("SELECT COUNT(*) AS n FROM transcripts").fetchone()["n"] == 1
    assert conn.execute("SELECT status FROM recordings").fetchone()["status"] == "done"
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE status != 'done'").fetchone()["n"] == 0
    )


def test_stt_rerun_replaces_transcript_without_duplicates(tmp_path: Path) -> None:
    """Re-running STT (crash replay / retranscribe) keeps exactly one transcript."""
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)
    JobRunner(settings).drain(conn)

    rec_id = conn.execute("SELECT id FROM recordings").fetchone()["id"]
    repository.enqueue_job(conn, JobType.STT, {"recording_id": rec_id})
    JobRunner(settings).drain(conn)

    assert conn.execute("SELECT COUNT(*) AS n FROM transcripts").fetchone()["n"] == 1
    counts = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT transcript_id) AS t FROM segments"
    ).fetchone()
    assert counts["t"] <= 1  # segments only ever reference the one live transcript


def test_diary_reaggregation_keeps_one_entry_per_day(tmp_path: Path) -> None:
    """Settle → aggregate → late re-run: still exactly one diary row + sidecar."""
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)
    JobRunner(settings).drain(conn)
    Scheduler(settings).tick(conn)
    JobRunner(settings).drain(conn)
    date = conn.execute("SELECT date FROM diary_entries").fetchone()["date"]

    # A crash replay (or manual resummarize) of the same day.
    repository.enqueue_job(conn, JobType.DIARY_AGGREGATE, {"date": date})
    JobRunner(settings).drain(conn)

    assert conn.execute("SELECT COUNT(*) AS n FROM diary_entries").fetchone()["n"] == 1
    assert (settings.core.resolved_data_dir / "diary" / f"{date}.md").is_file()


# --- transcode integrity (FR-3.3: a failed transcode never costs audio) ---


class _InvalidOutputTranscoder:
    """ffmpeg stand-in whose output never validates (truncated/corrupt opus)."""

    def __init__(self, _settings: object) -> None:
        pass

    def probe_duration(self, _path: Path) -> float:
        return 1.0

    def to_opus(self, _src: Path, dst: Path) -> None:
        dst.write_bytes(b"garbage")

    def validate(self, _path: Path, *, expected_duration: float | None = None) -> bool:
        return False


def test_invalid_transcode_keeps_original_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """transcode_only with a bad encode: original stays; a later good run replaces it."""
    settings = _settings(tmp_path, policy=TranscodePolicy.TRANSCODE_ONLY)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)

    monkeypatch.setattr(pipeline, "Transcoder", _InvalidOutputTranscoder)
    JobRunner(settings).drain(conn)

    rec = conn.execute("SELECT library_path FROM recordings").fetchone()
    assert rec["library_path"].endswith(".wav")  # original untouched
    assert Path(rec["library_path"]).read_bytes() == _AUDIO + b"\x00"
    assert not Path(rec["library_path"]).with_suffix(".opus").exists()  # garbage removed
    failed = conn.execute("SELECT status FROM jobs WHERE type = 'transcode'").fetchone()
    assert failed["status"] in ("failed", "parked")

    # ffmpeg fixed → retry succeeds and only then replaces the original.
    class _GoodTranscoder(_InvalidOutputTranscoder):
        def validate(self, _path: Path, *, expected_duration: float | None = None) -> bool:
            return True

        def to_opus(self, _src: Path, dst: Path) -> None:
            dst.write_bytes(b"OpusHead-fake")

    monkeypatch.setattr(pipeline, "Transcoder", _GoodTranscoder)
    assert repository.requeue_failed_jobs(conn) >= 1
    JobRunner(settings).drain(conn)
    rec = conn.execute("SELECT library_path, codec FROM recordings").fetchone()
    assert rec["library_path"].endswith(".opus")
    assert rec["codec"] == "opus"
    assert not Path(rec["library_path"]).with_suffix(".wav").exists()  # replaced after validation


def test_auto_delete_with_failed_transcode_loses_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """auto_delete + transcode_only + broken ffmpeg: the verified library original survives.

    The device source is deleted after its SHA-256-verified backup (FR-2.5); if the
    transcode then fails, the library original is still the safe copy — the chain
    never has a window where no verified copy exists.
    """
    settings = _settings(tmp_path, policy=TranscodePolicy.TRANSCODE_ONLY)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings, auto_delete=True)
    backup.run_backup(conn, device, vol, settings)
    assert not (vol / "clip0.wav").exists()  # source deleted after verified backup

    monkeypatch.setattr(pipeline, "Transcoder", _InvalidOutputTranscoder)
    JobRunner(settings).drain(conn)

    rec = conn.execute("SELECT library_path FROM recordings").fetchone()
    library_file = Path(rec["library_path"])
    assert library_file.is_file()
    assert library_file.read_bytes() == _AUDIO + b"\x00"  # bit-exact verified copy retained


# --- schema migrations (FR-9.3: old libraries upgrade in place, data intact) ---


def test_populated_v7_library_upgrades_to_latest(tmp_path: Path) -> None:
    """A pre-M4 database (schema 7) with data migrates forward losslessly."""
    path = tmp_path / "old.db"
    conn = db.connect(path)

    # Build the world as it was at schema 7 (pre kind/suggested_name/cloud_sync_log).
    old = dict(db.MIGRATIONS[:7])
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for version in sorted(old):
        for statement in old[version].split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))

    conn.execute(
        "INSERT INTO devices (id, name, audio_globs) VALUES ('dev-1', 'Old Recorder', '[]')"
    )
    conn.execute(
        "INSERT INTO recordings (id, device_id, source_path, sha256, size_bytes) "
        "VALUES ('rec-1', 'dev-1', 'a.wav', 'h1', 10)"
    )
    conn.execute("INSERT INTO speakers (display_name) VALUES ('kevin')")

    version = db.apply_migrations(conn)
    assert version == db.MIGRATIONS[-1][0]

    device = repository.find_device(conn, "dev-1")
    assert device is not None
    assert device.name == "Old Recorder"
    assert device.kind.value == "usb"  # migration default for pre-M4 rows
    speaker = repository.find_speaker(conn, 1)
    assert speaker is not None
    assert speaker.display_name == "kevin"
    assert speaker.suggested_name is None
    assert repository.list_cloud_sync_log(conn) == []  # new table exists and is queryable

    # Idempotent: running again is a no-op at the same version.
    assert db.apply_migrations(conn) == version


def test_failed_migration_rolls_back_completely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migration that dies mid-script leaves the DB at the previous version."""
    path = tmp_path / "x.db"
    conn = db.connect(path)
    last_good_version = db.MIGRATIONS[-1][0]
    broken = (*db.MIGRATIONS, (99, "CREATE TABLE ok_table (id INTEGER); SYNTAX ERROR HERE"))
    monkeypatch.setattr(db, "MIGRATIONS", broken)

    with pytest.raises(sqlite3.OperationalError):
        db.apply_migrations(conn)

    # The good statement in the failed migration must not have survived.
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ok_table'"
    ).fetchone()
    assert row is None
    version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()["v"]
    assert version == last_good_version


def test_transcripts_json_survives_pipeline_rerun(tmp_path: Path) -> None:
    """The on-disk transcript sidecar always matches the DB row after replays."""
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)
    JobRunner(settings).drain(conn)

    rec_id = conn.execute("SELECT id FROM recordings").fetchone()["id"]
    for _ in range(2):  # replay the whole tail twice
        repository.enqueue_job(conn, JobType.STT, {"recording_id": rec_id})
        JobRunner(settings).drain(conn)

    t = conn.execute("SELECT json_path FROM transcripts").fetchone()
    sidecars = list((settings.core.resolved_data_dir / "transcripts").iterdir())
    assert [Path(t["json_path"])] == sidecars  # exactly one sidecar, the referenced one
    assert json.loads(Path(t["json_path"]).read_text(encoding="utf-8"))["engine"] == "null"
