"""WebSocket relay + diary.updated emission from the pipeline."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from loomis.api.app import create_app
from loomis.core import db, repository
from loomis.core.config import (
    ApiSettings,
    BackupSettings,
    CoreSettings,
    DiarizeSettings,
    LlmSettings,
    Settings,
    SpeakerIdSettings,
    SttSettings,
)
from loomis.core.events import EventBus, drain
from loomis.core.models import (
    Device,
    JobType,
    Recording,
    RecordingKind,
    RecordingStatus,
    TranscodePolicy,
)
from loomis.pipeline.runner import JobRunner


def test_ws_relays_bus_events(tmp_path: Path) -> None:
    settings = Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        api=ApiSettings(run_daemon=False, serve_spa=False),
    )
    app = create_app(settings)
    with TestClient(app) as client, client.websocket_connect("/api/v1/ws") as websocket:
        app.state.bus.publish("job.updated", {"job_id": 1, "status": "done"})
        msg = websocket.receive_json()
    assert msg == {"type": "job.updated", "data": {"job_id": 1, "status": "done"}}


def _pipeline_settings(tmp_path: Path) -> Settings:
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


def test_diary_aggregate_emits_diary_updated(tmp_path: Path) -> None:
    settings = _pipeline_settings(tmp_path)
    conn = _conn(settings)
    repository.insert_device(conn, Device(id="dev-1", name="Recorder"))
    repository.insert_recording(
        conn,
        Recording(
            id="rec-1",
            device_id="dev-1",
            source_path="rec-1.wav",
            library_path="rec-1.wav",
            sha256="h1",
            size_bytes=1,
            recorded_at="2026-06-09T10:00:00+08:00",
            status=RecordingStatus.DONE,
        ),
    )
    repository.set_recording_kind(conn, "rec-1", RecordingKind.DIARY)
    repository.enqueue_job(conn, JobType.DIARY_AGGREGATE, {"date": "2026-06-09"})

    bus = EventBus()
    q = bus.subscribe()
    JobRunner(settings, bus=bus).drain(conn)

    events = drain(q)
    diary = [e for e in events if e.type == "diary.updated"]
    assert diary and diary[0].data == {"date": "2026-06-09"}
