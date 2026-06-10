"""Daemon background threads: the job runner drains the queue and emits events."""

from __future__ import annotations

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
from loomis.core.models import JobType
from loomis.daemon import Daemon


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        # tmp_path sources look like folders; skip the sync settle window in tests
        backup=BackupSettings(folder_settle_seconds=0.0),
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


def test_daemon_runs_enqueued_job_and_emits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Neutralize the device watcher so the test never touches real removable media.
    monkeypatch.setattr("loomis.ingest.watcher.removable_volumes", lambda: set())

    settings = _settings(tmp_path)
    conn = _conn(settings)
    # A diary_aggregate for an empty day is a clean no-op job: completes without any
    # recording/LLM, so it isolates the runner-thread + event wiring.
    repository.enqueue_job(conn, JobType.DIARY_AGGREGATE, {"date": "2099-01-01"})

    bus = EventBus()
    q = bus.subscribe()
    daemon = Daemon(settings, bus)
    daemon.start()
    try:
        status = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            row = conn.execute("SELECT status FROM jobs LIMIT 1").fetchone()
            status = row["status"] if row else None
            if status == "done":
                break
            time.sleep(0.05)
    finally:
        daemon.stop()

    assert status == "done"
    assert "job.updated" in {e.type for e in drain(q)}


def test_daemon_start_stop_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("loomis.ingest.watcher.removable_volumes", lambda: set())
    settings = _settings(tmp_path)
    _conn(settings)  # ensure the DB exists for the watcher thread's connection

    daemon = Daemon(settings, EventBus())
    daemon.start()
    daemon.stop()  # must join without hanging
    assert daemon._threads == []  # noqa: SLF001 (white-box check that threads were cleared)
