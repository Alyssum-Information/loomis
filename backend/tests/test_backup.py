"""M1 backup-core tests: registration, the safety spine, idempotency, cleanup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loomis import backup, db, repository
from loomis.config import CoreSettings, Settings
from loomis.devicefile import DeviceFile, device_file_path
from loomis.storage import sha256_file

_AUDIO = b"RIFF\x00\x00\x00\x00WAVEfmt fake-audio-bytes-for-testing" * 16


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
