"""Schema migration + domain-model round-trip tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from loomis.core import db
from loomis.core.models import Device, Recording, RecordingStatus


def _fresh(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "loomis.db")
    db.apply_migrations(conn)
    return conn


_LATEST_VERSION = len(db.MIGRATIONS)


def test_migration_creates_tables(tmp_path: Path) -> None:
    conn = _fresh(tmp_path)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"devices", "recordings", "jobs", "quarantine", "schema_migrations"} <= names


def test_migrations_idempotent(tmp_path: Path) -> None:
    conn = _fresh(tmp_path)
    assert db.apply_migrations(conn) == _LATEST_VERSION
    # re-running applies nothing and keeps version stable
    assert db.apply_migrations(conn) == _LATEST_VERSION


def test_device_round_trip(tmp_path: Path) -> None:
    conn = _fresh(tmp_path)
    conn.execute(
        "INSERT INTO devices (id, name, audio_globs, auto_delete, transcode_opts) "
        "VALUES (?, ?, ?, ?, ?)",
        ("dev-1", "Recorder", json.dumps(["**/*.wav"]), 1, json.dumps({"bitrate": "16k"})),
    )
    row = conn.execute("SELECT * FROM devices WHERE id = 'dev-1'").fetchone()
    dev = Device.from_row(row)
    assert dev.name == "Recorder"
    assert dev.audio_globs == ["**/*.wav"]
    assert dev.auto_delete is True
    assert dev.transcode_opts == {"bitrate": "16k"}


def test_recording_dedupe_unique(tmp_path: Path) -> None:
    conn = _fresh(tmp_path)
    conn.execute("INSERT INTO devices (id, name) VALUES ('dev-1', 'R')")
    conn.execute(
        "INSERT INTO recordings (id, device_id, source_path, sha256, size_bytes) "
        "VALUES ('rec-1', 'dev-1', '/x.wav', 'abc', 10)"
    )
    # same (device_id, sha256) must be rejected
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO recordings (id, device_id, source_path, sha256, size_bytes) "
            "VALUES ('rec-2', 'dev-1', '/y.wav', 'abc', 10)"
        )
    rec = Recording.from_row(conn.execute("SELECT * FROM recordings WHERE id = 'rec-1'").fetchone())
    assert rec.status is RecordingStatus.IMPORTED
    assert rec.source_deleted is False
