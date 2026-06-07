"""M1 backup-core tests: registration, the safety spine, idempotency, cleanup."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from loomis import backup, db, repository
from loomis.config import CoreSettings, Settings
from loomis.devicefile import DeviceFile, device_file_path
from loomis.storage import sha256_file

_AUDIO = b"RIFF\x00\x00\x00\x00WAVEfmt fake-audio-bytes-for-testing" * 16


def _write_device_json(volume: Path, **overrides: object) -> None:
    """Hand-author a minimal device.json on the volume (FR-1.6)."""
    payload: dict[str, object] = {
        "schema": "loomis.device/v1",
        "device_id": "hand-authored-1",
        "name": "Hand Recorder",
        "registered_at": "2026-06-06T12:00:00+08:00",
        "loomis_version": "0.1.0",
    }
    payload.update(overrides)
    path = device_file_path(volume)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(core=CoreSettings(data_dir=tmp_path / "data"))


@pytest.fixture
def conn(settings: Settings) -> sqlite3.Connection:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    c = db.connect(data_dir / "loomis.db")
    db.apply_migrations(c)
    return c


@pytest.fixture
def volume(tmp_path: Path) -> Path:
    vol = tmp_path / "RECORDER"
    (vol / "REC").mkdir(parents=True)
    (vol / "REC" / "clip1.wav").write_bytes(_AUDIO)
    return vol


def test_register_writes_device_json_and_db_row(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    device = backup.register_or_load_device(conn, volume, settings, name="Tester")

    path = device_file_path(volume)
    assert path.exists()
    df = DeviceFile.load(path)
    assert df.device_id == device.id
    assert df.schema_ == "loomis.device/v1"
    assert repository.find_device(conn, device.id) is not None


def test_register_is_idempotent(conn: sqlite3.Connection, volume: Path, settings: Settings) -> None:
    first = backup.register_or_load_device(conn, volume, settings)
    second = backup.register_or_load_device(conn, volume, settings)

    assert first.id == second.id
    rows = conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()
    assert rows["n"] == 1


def test_readonly_volume_registers_once_via_serial(
    conn: sqlite3.Connection,
    volume: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # device.json cannot be written (read-only): registration must still resolve to
    # one stable row across reconnects via the volume-identity fallback (FR-1.5).
    def boom(self: DeviceFile, path: Path) -> None:
        raise OSError("read-only volume")

    monkeypatch.setattr(DeviceFile, "write", boom)
    first = backup.register_or_load_device(conn, volume, settings)
    second = backup.register_or_load_device(conn, volume, settings)

    assert first.id == second.id
    assert first.volume_serial  # identity fallback recorded
    assert not device_file_path(volume).exists()
    assert conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"] == 1


def test_backup_imports_and_verifies(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    device = backup.register_or_load_device(conn, volume, settings)
    report = backup.run_backup(conn, device, volume, settings)

    assert report.imported == 1
    rec = conn.execute("SELECT * FROM recordings").fetchone()
    lib = Path(rec["library_path"])
    assert lib.is_file()
    assert lib.read_bytes() == _AUDIO
    assert rec["sha256"] == sha256_file(volume / "REC" / "clip1.wav")
    # Step 8 — a pipeline job was enqueued for the new recording.
    job = conn.execute("SELECT * FROM jobs").fetchone()
    assert job["type"] == "stt"


def test_reimport_is_idempotent(conn: sqlite3.Connection, volume: Path, settings: Settings) -> None:
    device = backup.register_or_load_device(conn, volume, settings)
    backup.run_backup(conn, device, volume, settings)
    report2 = backup.run_backup(conn, device, volume, settings)

    assert report2.imported == 0
    assert report2.skipped == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 1


def test_duplicate_content_deduped_by_hash(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    # Same bytes, different filename → caught by the SHA-256 ledger check.
    (volume / "REC" / "copy.wav").write_bytes(_AUDIO)
    device = backup.register_or_load_device(conn, volume, settings)
    report = backup.run_backup(conn, device, volume, settings)

    assert report.imported == 1
    assert report.duplicates == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 1


def test_hash_mismatch_quarantines_and_keeps_source(
    conn: sqlite3.Connection,
    volume: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate a corrupt copy: hashes differ between source and the staged copy.
    def fake_hash(path: Path) -> str:
        return "staged" if "staging" in str(path) else "source"

    monkeypatch.setattr(backup, "sha256_file", fake_hash)
    device = backup.register_or_load_device(conn, volume, settings)
    report = backup.run_backup(conn, device, volume, settings)

    assert report.quarantined == 1
    assert report.imported == 0
    assert (volume / "REC" / "clip1.wav").exists()  # source never touched
    quarantine = settings.core.resolved_data_dir / "quarantine"
    assert any(quarantine.iterdir())
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 0
    # The event is queryable, not just logged.
    q = conn.execute("SELECT * FROM quarantine").fetchone()
    assert q["reason"] == "hash_mismatch"
    assert q["source_path"] == str(volume / "REC" / "clip1.wav")


def test_auto_delete_removes_source_after_verified_backup(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    device = backup.register_or_load_device(conn, volume, settings, auto_delete=True)
    src = volume / "REC" / "clip1.wav"
    report = backup.run_backup(conn, device, volume, settings)

    assert report.imported == 1
    assert report.deleted == 1
    assert not src.exists()
    rec = conn.execute("SELECT * FROM recordings").fetchone()
    assert rec["source_deleted"] == 1


def test_run_clears_orphaned_staging_files(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    staging = settings.core.resolved_data_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    orphan = staging / "deadbeef.wav"
    orphan.write_bytes(b"debris from a crashed run")

    device = backup.register_or_load_device(conn, volume, settings)
    backup.run_backup(conn, device, volume, settings)

    assert not orphan.exists()  # debris discarded before the run


def test_non_audio_and_device_dir_excluded(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    (volume / "REC" / "notes.txt").write_bytes(b"not audio")
    device = backup.register_or_load_device(conn, volume, settings)
    # device.json now lives under .loomis/ and must never be imported.
    report = backup.run_backup(conn, device, volume, settings)

    assert report.imported == 1  # only clip1.wav
    paths = [r["source_path"] for r in conn.execute("SELECT source_path FROM recordings")]
    assert all(".loomis" not in p and not p.endswith(".txt") for p in paths)


def test_commit_failure_leaves_no_orphan_library_file(
    conn: sqlite3.Connection,
    volume: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = backup.register_or_load_device(conn, volume, settings)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(repository, "insert_recording", boom)
    report = backup.run_backup(conn, device, volume, settings)

    assert report.imported == 0
    assert report.errors == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 0
    library = settings.core.resolved_data_dir / "library"
    assert not any(library.rglob("*.wav"))  # rolled back — no orphaned committed file


def test_low_disk_space_skips_and_keeps_source(
    conn: sqlite3.Connection,
    volume: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: SimpleNamespace(free=100))
    device = backup.register_or_load_device(conn, volume, settings)
    device.min_free_bytes = 10_000  # demand far more headroom than the fake free space

    report = backup.run_backup(conn, device, volume, settings)

    assert report.imported == 0
    assert report.errors == 1
    assert (volume / "REC" / "clip1.wav").exists()  # source untouched


def test_hand_authored_device_json_is_accepted(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    _write_device_json(volume)  # FR-1.6: a user-written file must validate + be used as-is
    device = backup.register_or_load_device(conn, volume, settings)

    assert device.id == "hand-authored-1"
    assert repository.find_device(conn, "hand-authored-1") is not None


def test_transcode_policy_enqueues_transcode_first(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    _write_device_json(volume, transcode={"policy": "transcode_keep"})
    device = backup.register_or_load_device(conn, volume, settings)
    backup.run_backup(conn, device, volume, settings)

    job = conn.execute("SELECT type FROM jobs").fetchone()
    assert job["type"] == "transcode"  # not stt — policy keeps a transcode in the chain


def test_multiple_devices_register_separately(
    conn: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    for i in (1, 2):
        vol = tmp_path / f"REC{i}"
        (vol / "a").mkdir(parents=True)
        (vol / "a" / "clip.wav").write_bytes(_AUDIO + bytes([i]))
        backup.register_or_load_device(conn, vol, settings)

    assert conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"] == 2


def test_changed_source_at_same_path_is_reimported(
    conn: sqlite3.Connection, volume: Path, settings: Settings
) -> None:
    # A recorder may reuse a filename: same path + same size, different content. The
    # mtime in the pre-check key stops it being silently skipped (05 §4).
    device = backup.register_or_load_device(conn, volume, settings)
    backup.run_backup(conn, device, volume, settings)

    src = volume / "REC" / "clip1.wav"
    original_mtime = src.stat().st_mtime
    src.write_bytes(bytes(len(_AUDIO)))  # different bytes, identical length
    os.utime(src, (original_mtime, original_mtime + 10))  # ensure mtime differs

    report = backup.run_backup(conn, device, volume, settings)
    assert report.imported == 1  # not skipped
    assert report.skipped == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 2


def test_cli_backup_entry_point(
    tmp_path: Path, volume: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loomis.cli import main

    monkeypatch.setenv("LOOMIS_CORE__DATA_DIR", str(tmp_path / "clidata"))
    rc = main(["backup", str(volume)])

    assert rc == 0
    c = sqlite3.connect(tmp_path / "clidata" / "loomis.db")
    assert c.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1


def test_cli_survives_malformed_device_json(
    tmp_path: Path, volume: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A corrupt device.json must be skipped (logged), not crash the run, and never
    # be overwritten.
    from loomis.cli import main

    path = device_file_path(volume)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not valid json", encoding="utf-8")

    monkeypatch.setenv("LOOMIS_CORE__DATA_DIR", str(tmp_path / "clidata2"))
    rc = main(["backup", str(volume)])

    assert rc == 0  # handled, not crashed
    assert path.read_text(encoding="utf-8") == "{ this is not valid json"  # untouched
    c = sqlite3.connect(tmp_path / "clidata2" / "loomis.db")
    assert c.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 0
