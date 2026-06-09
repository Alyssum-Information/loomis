"""Pipeline steps end-to-end via the job runner: STT persistence + transcode routing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from loomis import backup, db, pipeline, repository
from loomis.config import (
    CoreSettings,
    DiarizeSettings,
    LlmSettings,
    Settings,
    SpeakerIdSettings,
    SttSettings,
)
from loomis.devicefile import device_file_path
from loomis.jobs import JobRunner

_AUDIO = b"RIFF\x00\x00\x00\x00WAVEfake-audio" * 8


def _settings(tmp_path: Path) -> Settings:
    # Null engines/provider keep the test offline (no torch/whisperx/pyannote/network).
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        stt=SttSettings(engine="null"),
        diarize=DiarizeSettings(engine="null"),
        speaker_id=SpeakerIdSettings(engine="null"),
        llm=LlmSettings(provider="null"),
    )


def _conn(settings: Settings) -> sqlite3.Connection:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    c = db.connect(data_dir / "loomis.db")
    db.apply_migrations(c)
    return c


def _volume(tmp_path: Path, **device_json: object) -> Path:
    vol = tmp_path / "REC"
    (vol / "a").mkdir(parents=True)
    (vol / "a" / "clip.wav").write_bytes(_AUDIO)
    if device_json:
        path = device_file_path(vol)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "schema": "loomis.device/v1",
            "device_id": "dev-1",
            "name": "Recorder",
            "registered_at": "2026-06-06T12:00:00+08:00",
            "loomis_version": "0.1.0",
        }
        payload.update(device_json)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return vol


def test_backup_then_stt_persists_transcript(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)

    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)  # keep_original → enqueues stt

    processed = JobRunner(settings).drain(conn)
    assert processed == 5  # stt → diarize → speaker_id → classify → diary_aggregate

    t = conn.execute("SELECT * FROM transcripts").fetchone()
    assert t is not None
    assert t["engine"] == "null"
    assert Path(t["json_path"]).is_file()
    assert json.loads(Path(t["json_path"]).read_text(encoding="utf-8"))["engine"] == "null"
    rec = conn.execute("SELECT status FROM recordings").fetchone()
    assert rec["status"] == "done"


class _FakeTranscoder:
    """Stand-in for ffmpeg: 'produces' a valid opus file without the binary."""

    def __init__(self, _settings: object) -> None:
        pass

    def probe_duration(self, _path: Path) -> float:
        return 1.0

    def to_opus(self, _src: Path, dst: Path) -> None:
        dst.write_bytes(b"OpusHead-fake")

    def validate(self, _path: Path, *, expected_duration: float | None = None) -> bool:
        return True


def test_transcode_only_replaces_original_then_transcribes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path, transcode={"policy": "transcode_only"})
    monkeypatch.setattr(pipeline, "Transcoder", _FakeTranscoder)

    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)  # policy != keep_original → enqueues transcode

    processed = JobRunner(settings).drain(conn)
    assert processed == 6  # transcode → stt → diarize → speaker_id → classify → diary_aggregate

    rec = conn.execute("SELECT library_path, codec, status FROM recordings").fetchone()
    assert rec["codec"] == "opus"
    assert rec["library_path"].endswith(".opus")
    assert Path(rec["library_path"]).is_file()
    assert rec["status"] == "done"
    # transcode_only deletes the original (the validated opus is the kept copy).
    assert not Path(rec["library_path"]).with_suffix(".wav").exists()
    assert conn.execute("SELECT COUNT(*) AS n FROM transcripts").fetchone()["n"] == 1


def test_failed_handler_parks_and_marks_recording_failed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    device = backup.register_or_load_device(conn, vol, settings)
    backup.run_backup(conn, device, vol, settings)

    # A handler that always fails should burn attempts and park, not loop forever.
    def boom(_ctx: object, _job: object) -> None:
        raise RuntimeError("nope")

    from loomis.models import JobType

    runner = JobRunner(settings, handlers={JobType.STT: boom})
    runner.drain(conn)

    job = conn.execute("SELECT status FROM jobs WHERE type='stt'").fetchone()
    assert job["status"] == "parked"
    # Parked job must surface on the recording, not leave it stuck "processing".
    rec = conn.execute("SELECT status FROM recordings").fetchone()
    assert rec["status"] == "failed"


class _ExplodingTranscoder:
    """Fails if asked to transcode — proves the idempotency guard skips re-transcode."""

    def __init__(self, _settings: object) -> None:
        pass

    def probe_duration(self, _path: Path) -> float:
        return 1.0

    def to_opus(self, _src: Path, _dst: Path) -> None:
        raise AssertionError("must not re-transcode an already-Opus recording")

    def validate(self, _path: Path, *, expected_duration: float | None = None) -> bool:
        return True


def test_transcode_retry_on_already_opus_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a reclaimed transcode job after the recording was already transcoded:
    # the guard must skip ffmpeg (avoiding src==dst corruption) and hand off to STT.
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path, transcode={"policy": "transcode_only"})
    device = backup.register_or_load_device(conn, vol, settings)
    report = backup.run_backup(conn, device, vol, settings)
    rec_id = report.imported_ids[0]

    # Pretend the prior transcode already ran: recording is Opus, transcode re-queued.
    opus = tmp_path / "data" / "already.opus"
    opus.parent.mkdir(parents=True, exist_ok=True)
    opus.write_bytes(b"OpusHead-fake")
    repo_path = str(opus)
    conn.execute(
        "UPDATE recordings SET library_path = ?, codec = 'opus' WHERE id = ?", (repo_path, rec_id)
    )
    from loomis.models import JobType

    repository.enqueue_job(conn, JobType.TRANSCODE, {"recording_id": rec_id})
    monkeypatch.setattr(pipeline, "Transcoder", _ExplodingTranscoder)

    JobRunner(settings).drain(conn)  # must not raise

    rec = conn.execute("SELECT status FROM recordings").fetchone()
    assert rec["status"] == "done"
    assert opus.read_bytes() == b"OpusHead-fake"  # untouched — never re-transcoded
    assert conn.execute("SELECT COUNT(*) AS n FROM transcripts").fetchone()["n"] == 1
