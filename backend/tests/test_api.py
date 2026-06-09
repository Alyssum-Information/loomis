"""REST read surface: endpoints return seeded data, 404s use the error envelope."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loomis import db, repository
from loomis.app import create_app
from loomis.config import ApiSettings, CoreSettings, Settings
from loomis.models import (
    Device,
    DiaryEntry,
    Meeting,
    Recording,
    RecordingStatus,
    Segment,
    Transcript,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        api=ApiSettings(run_daemon=False, serve_spa=False),
    )


def _seed(settings: Settings) -> None:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(data_dir / "loomis.db")
    db.apply_migrations(conn)
    try:
        repository.insert_device(conn, Device(id="dev-1", name="Recorder"))
        audio = data_dir / "rec-1.wav"
        audio.write_bytes(b"RIFFfake-wav-bytes")
        repository.insert_recording(
            conn,
            Recording(
                id="rec-1",
                device_id="dev-1",
                source_path="rec-1.wav",
                library_path=str(audio),
                sha256="h1",
                size_bytes=audio.stat().st_size,
                recorded_at="2026-06-09T10:00:00+08:00",
                status=RecordingStatus.DONE,
            ),
        )
        repository.insert_recording(
            conn,
            Recording(
                id="rec-2",
                device_id="dev-1",
                source_path="rec-2.wav",
                library_path=None,
                sha256="h2",
                size_bytes=1,
                recorded_at="2026-06-08T09:00:00+08:00",
                status=RecordingStatus.IMPORTED,
            ),
        )
        sid = repository.create_speaker(conn)
        tid = "t-1"
        repository.replace_transcript(
            conn,
            Transcript(
                id=tid, recording_id="rec-1", engine="null", text="hello world meeting notes"
            ),
            [
                Segment(
                    transcript_id=tid, idx=0, start_s=0.0, end_s=1.0, speaker_id=sid, text="hello"
                )
            ],
        )
        repository.replace_diary_entry(
            conn,
            DiaryEntry(
                id="d-1",
                date="2026-06-09",
                title="A day",
                metadata={"narrative_markdown": "today I tested the api"},
            ),
            ["rec-1"],
        )
        repository.insert_meeting(
            conn,
            Meeting(
                id="m-1",
                title="Standup",
                occurred_on="2026-06-09",
                metadata={"summary_markdown": "we discussed search"},
            ),
            recording_ids=["rec-1"],
            participant_ids=[sid],
        )
    finally:
        conn.close()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = _settings(tmp_path)
    _seed(settings)
    with TestClient(create_app(settings)) as c:
        yield c


def test_list_and_get_device(client: TestClient) -> None:
    devices = client.get("/api/v1/devices").json()
    assert [d["id"] for d in devices] == ["dev-1"]
    assert client.get("/api/v1/devices/dev-1").json()["name"] == "Recorder"


def test_unknown_device_uses_error_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/devices/nope")
    assert resp.status_code == 404
    assert resp.json() == {"error": {"code": 404, "message": "device not found"}}


def test_recordings_pagination(client: TestClient) -> None:
    page1 = client.get("/api/v1/recordings", params={"limit": 1}).json()
    assert len(page1["items"]) == 1
    assert page1["items"][0]["id"] == "rec-1"  # newest first
    assert page1["next_cursor"] == "1"
    page2 = client.get("/api/v1/recordings", params={"limit": 1, "cursor": "1"}).json()
    assert page2["items"][0]["id"] == "rec-2"
    assert page2["next_cursor"] is None


def test_recordings_filter_by_status(client: TestClient) -> None:
    items = client.get("/api/v1/recordings", params={"status": "imported"}).json()["items"]
    assert [r["id"] for r in items] == ["rec-2"]


def test_transcript_and_audio(client: TestClient) -> None:
    detail = client.get("/api/v1/recordings/rec-1/transcript").json()
    assert detail["transcript"]["recording_id"] == "rec-1"
    assert detail["segments"][0]["text"] == "hello"

    audio = client.get("/api/v1/recordings/rec-1/audio")
    assert audio.status_code == 200
    assert audio.content == b"RIFFfake-wav-bytes"

    # rec-2 has no library file → 404
    assert client.get("/api/v1/recordings/rec-2/audio").status_code == 404


def test_timeline_diary_meeting(client: TestClient) -> None:
    timeline = client.get("/api/v1/timeline").json()
    day = next(d for d in timeline if d["date"] == "2026-06-09")
    assert day["has_diary"] is True
    assert day["meeting_count"] == 1

    assert client.get("/api/v1/diary/2026-06-09").json()["title"] == "A day"
    assert client.get("/api/v1/meetings/m-1").json()["title"] == "Standup"


def test_speakers_and_search(client: TestClient) -> None:
    assert len(client.get("/api/v1/speakers").json()) == 1

    hits = client.get("/api/v1/search", params={"q": "meeting"}).json()
    kinds = {h["ref_kind"] for h in hits}
    # "meeting" appears in the transcript text and the meeting summary.
    assert "recording" in kinds
    assert hits  # non-empty


def test_jobs_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
