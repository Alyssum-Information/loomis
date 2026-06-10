"""Folder sources: registration, settle window, daemon poll (FR-1.11 … FR-1.13)."""

from __future__ import annotations

import os
import sqlite3
import time
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
)
from loomis.core.events import EventBus, drain
from loomis.core.models import DeviceKind, TranscodePolicy
from loomis.daemon import Daemon
from loomis.ingest import backup
from loomis.ingest.devicefile import DeviceFile, device_file_path

_AUDIO = b"RIFF\x00\x00\x00\x00WAVEfmt fake-audio-bytes-for-testing" * 16


def _settings(tmp_path: Path, **backup_overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "folder_settle_seconds": 0.0,
        "folder_poll_interval_s": 0.05,
        # fake RIFF bytes can't survive a real ffmpeg transcode; keep originals
        "transcode_policy": TranscodePolicy.KEEP_ORIGINAL,
    }
    defaults.update(backup_overrides)
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        backup=BackupSettings(**defaults),  # type: ignore[arg-type]
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


def _folder(tmp_path: Path, *, with_audio: bool = True) -> Path:
    folder = tmp_path / "PhoneSync"
    folder.mkdir(parents=True, exist_ok=True)
    if with_audio:
        (folder / "memo.wav").write_bytes(_AUDIO)
    return folder


def test_register_folder_source_writes_marker_and_row(tmp_path: Path) -> None:
    # Even with a global auto-delete default, a folder source must default to off
    # (FR-1.13) — the folder usually belongs to a sync tool.
    settings = _settings(tmp_path, auto_delete_after_backup=True)
    conn = _conn(settings)
    folder = _folder(tmp_path, with_audio=False)

    device = backup.register_device(conn, folder, settings)

    assert device.kind == DeviceKind.FOLDER
    assert device.source_path == str(folder.resolve())
    assert device.auto_delete is False
    df = DeviceFile.load(device_file_path(folder))
    assert df.kind == DeviceKind.FOLDER
    assert repository.list_folder_sources(conn) and (
        repository.list_folder_sources(conn)[0].id == device.id
    )


def test_list_folder_sources_excludes_unregistered(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    folder = _folder(tmp_path, with_audio=False)
    device = backup.register_device(conn, folder, settings)

    assert backup.unregister_device(conn, device.id) is True
    assert repository.list_folder_sources(conn) == []


def test_settle_window_defers_fresh_files(tmp_path: Path) -> None:
    # A file whose mtime is inside the settle window is left alone (a sync tool may
    # still be writing it); once quiet, the next pass imports it (ADR-0012).
    settings = _settings(tmp_path, folder_settle_seconds=3600.0)
    conn = _conn(settings)
    folder = _folder(tmp_path)
    device = backup.register_device(conn, folder, settings)

    report = backup.run_backup(conn, device, folder, settings)
    assert report.imported == 0
    assert report.skipped == 1

    src = folder / "memo.wav"
    aged = time.time() - 7200
    os.utime(src, (aged, aged))
    report = backup.run_backup(conn, device, folder, settings)
    assert report.imported == 1


def test_daemon_polls_folder_and_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("loomis.ingest.watcher.removable_volumes", lambda: set())
    settings = _settings(tmp_path)
    conn = _conn(settings)
    folder = _folder(tmp_path)
    backup.register_device(conn, folder, settings)

    bus = EventBus()
    q = bus.subscribe()
    daemon = Daemon(settings, bus)
    daemon.start()
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 1:
                break
            time.sleep(0.05)
        else:
            pytest.fail("daemon did not import the folder recording in time")
    finally:
        daemon.stop()

    assert "recording.added" in {e.type for e in drain(q)}
    row = conn.execute("SELECT library_path, source_deleted FROM recordings").fetchone()
    assert row["library_path"]
    assert Path(row["library_path"]).is_file()
    assert row["source_deleted"] == 0  # folder sources never delete by default
    assert (folder / "memo.wav").exists()
