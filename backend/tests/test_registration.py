"""Opt-in registration: only registered devices import; register/unregister round-trip."""

from __future__ import annotations

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
)
from loomis.core.events import EventBus, drain
from loomis.core.models import TranscodePolicy
from loomis.daemon import Daemon
from loomis.ingest import backup
from loomis.ingest.devicefile import device_file_path


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        # tmp_path sources look like folders; skip the sync settle window in tests
        backup=BackupSettings(
            folder_settle_seconds=0.0,
            # fake RIFF bytes can't survive a real ffmpeg transcode; keep originals
            transcode_policy=TranscodePolicy.KEEP_ORIGINAL,
        ),
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


def _volume(tmp_path: Path, *, with_audio: bool = False) -> Path:
    vol = tmp_path / "REC"
    vol.mkdir(parents=True, exist_ok=True)
    if with_audio:
        (vol / "clip.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfake" * 4)
    return vol


def test_resolve_device_is_none_for_unregistered(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    assert backup.resolve_device(conn, _volume(tmp_path)) is None


def test_register_then_resolve(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)

    device = backup.register_device(conn, vol, settings, name="Mine")
    assert device.registered is True
    assert device_file_path(vol).is_file()

    resolved = backup.resolve_device(conn, vol)
    assert resolved is not None
    assert resolved.id == device.id
    assert resolved.registered is True


def test_unregister_keeps_recordings_drops_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path)
    # The temp volume isn't real removable media; present it as one so registration,
    # the marker-removal scan, and the serial fallback all see a USB device.
    monkeypatch.setattr(backup, "removable_volumes", lambda: {vol})
    device = backup.register_device(conn, vol, settings)

    assert backup.unregister_device(conn, device.id) is True
    assert not device_file_path(vol).exists()  # marker removed (volume connected)

    again = repository.find_device(conn, device.id)
    assert again is not None  # row kept
    assert again.registered is False
    # a resolved-but-unregistered device must not be importable
    resolved = backup.resolve_device(conn, vol)
    assert resolved is not None and resolved.registered is False


def test_unregister_unknown_returns_false(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    assert backup.unregister_device(conn, "nope") is False


def test_daemon_skips_unregistered_volume(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path, with_audio=True)

    bus = EventBus()
    q = bus.subscribe()
    Daemon(settings, bus)._on_connect(conn, vol)  # noqa: SLF001 (white-box: direct callback)

    events = drain(q)
    assert any(e.type == "device.connected" and e.data["registered"] is False for e in events)
    assert not any(e.type == "recording.added" for e in events)
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 0


def test_daemon_imports_registered_volume(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    vol = _volume(tmp_path, with_audio=True)
    backup.register_device(conn, vol, settings)

    bus = EventBus()
    q = bus.subscribe()
    Daemon(settings, bus)._on_connect(conn, vol)  # noqa: SLF001 (white-box: direct callback)

    events = drain(q)
    assert any(e.type == "device.connected" and e.data["registered"] is True for e in events)
    assert any(e.type == "recording.added" for e in events)
    assert conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"] == 1
