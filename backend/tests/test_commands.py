"""Command endpoints: quick writes, 202+job enqueues, and merge/split job effects."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loomis import db, repository
from loomis.app import create_app
from loomis.config import (
    ApiSettings,
    CoreSettings,
    DiarizeSettings,
    LlmSettings,
    Settings,
    SpeakerIdSettings,
    SttSettings,
)
from loomis.jobs import JobRunner
from loomis.models import (
    JobStatus,
    JobType,
    Recording,
    RecordingStatus,
    Segment,
    Transcript,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        api=ApiSettings(run_daemon=False, serve_spa=False),
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


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[tuple[TestClient, Settings]]:
    settings = _settings(tmp_path)
    _conn(settings).close()  # create + migrate the DB up front
    with TestClient(create_app(settings)) as client:
        yield client, settings


def test_register_device(ctx: tuple[TestClient, Settings], tmp_path: Path) -> None:
    client, _ = ctx
    volume = tmp_path / "REC"
    volume.mkdir()
    resp = client.post(
        "/api/v1/devices/register", json={"volume": str(volume), "name": "My Recorder"}
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "My Recorder"
    assert (volume / ".loomis" / "device.json").is_file()
    assert any(d["name"] == "My Recorder" for d in client.get("/api/v1/devices").json())


def test_register_missing_volume_404(ctx: tuple[TestClient, Settings], tmp_path: Path) -> None:
    client, _ = ctx
    resp = client.post("/api/v1/devices/register", json={"volume": str(tmp_path / "nope")})
    assert resp.status_code == 404


def test_register_then_unregister(
    ctx: tuple[TestClient, Settings], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loomis import backup

    client, _ = ctx
    volume = tmp_path / "REC"
    volume.mkdir()
    device_id = client.post("/api/v1/devices/register", json={"volume": str(volume)}).json()["id"]
    assert client.get(f"/api/v1/devices/{device_id}").json()["registered"] is True

    # Make the marker-removal scan find the temp volume (not real removable media).
    monkeypatch.setattr(backup, "removable_volumes", lambda: {volume})
    assert client.delete(f"/api/v1/devices/{device_id}").status_code == 204
    assert not (volume / ".loomis" / "device.json").exists()
    assert client.get(f"/api/v1/devices/{device_id}").json()["registered"] is False


def test_unregister_unknown_404(ctx: tuple[TestClient, Settings]) -> None:
    client, _ = ctx
    assert client.delete("/api/v1/devices/nope").status_code == 404


def test_patch_speaker_rename(ctx: tuple[TestClient, Settings]) -> None:
    client, settings = ctx
    conn = _conn(settings)
    sid = repository.create_speaker(conn)
    conn.close()

    resp = client.patch(
        f"/api/v1/speakers/{sid}", json={"display_name": "Kevin", "is_provisional": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Kevin"
    assert body["is_provisional"] is False


def test_patch_unknown_speaker_404(ctx: tuple[TestClient, Settings]) -> None:
    client, _ = ctx
    assert client.patch("/api/v1/speakers/999", json={"display_name": "x"}).status_code == 404


def _seed_speaker_with_recording(conn: sqlite3.Connection, speaker_id: int, rec_id: str) -> None:
    repository.insert_recording(
        conn,
        Recording(
            id=rec_id,
            device_id="dev-1",
            source_path=f"{rec_id}.wav",
            library_path=f"{rec_id}.wav",
            sha256=rec_id,
            size_bytes=1,
            status=RecordingStatus.DONE,
        ),
    )
    tid = f"t-{rec_id}"
    repository.replace_transcript(
        conn,
        Transcript(id=tid, recording_id=rec_id, engine="null", text="hi"),
        [
            Segment(
                transcript_id=tid,
                idx=0,
                start_s=0.0,
                end_s=1.0,
                speaker_id=speaker_id,
                text="hi",
            )
        ],
    )
    repository.add_voiceprint(
        conn,
        speaker_id,
        (0.1, 0.2, 0.3, 0.4),
        source_recording_id=rec_id,
        source_label="SPEAKER_00",
    )


def test_merge_speakers_job(ctx: tuple[TestClient, Settings]) -> None:
    client, settings = ctx
    conn = _conn(settings)
    from loomis.models import Device

    repository.insert_device(conn, Device(id="dev-1", name="R"))
    s1 = repository.create_speaker(conn)
    s2 = repository.create_speaker(conn)
    _seed_speaker_with_recording(conn, s1, "rec-1")

    resp = client.post("/api/v1/speakers/merge", json={"source_id": s1, "target_id": s2})
    assert resp.status_code == 202

    JobRunner(settings).drain(conn)

    assert repository.find_speaker(conn, s1) is None  # source folded in + deleted
    seg = conn.execute("SELECT speaker_id FROM segments").fetchone()
    assert seg["speaker_id"] == s2
    vp = conn.execute("SELECT speaker_id FROM voiceprints").fetchone()
    assert vp["speaker_id"] == s2
    conn.close()


def test_split_speaker_job(ctx: tuple[TestClient, Settings]) -> None:
    client, settings = ctx
    conn = _conn(settings)
    from loomis.models import Device

    repository.insert_device(conn, Device(id="dev-1", name="R"))
    s1 = repository.create_speaker(conn)
    _seed_speaker_with_recording(conn, s1, "rec-1")
    _seed_speaker_with_recording(conn, s1, "rec-2")

    resp = client.post(f"/api/v1/speakers/{s1}/split", json={"recording_id": "rec-1"})
    assert resp.status_code == 202

    JobRunner(settings).drain(conn)

    # rec-1's segment moved to a new speaker; rec-2 stays with s1.
    rows = {
        r["recording_id"]: r["speaker_id"]
        for r in conn.execute(
            "SELECT t.recording_id, s.speaker_id FROM segments s "
            "JOIN transcripts t ON s.transcript_id = t.id"
        ).fetchall()
    }
    assert rows["rec-2"] == s1
    assert rows["rec-1"] != s1
    conn.close()


def test_diary_resummarize_enqueues(ctx: tuple[TestClient, Settings]) -> None:
    client, settings = ctx
    resp = client.post("/api/v1/diary/2026-06-09/resummarize")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    conn = _conn(settings)
    row = conn.execute("SELECT type FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    assert row["type"] == "diary_aggregate"


def test_retry_job(ctx: tuple[TestClient, Settings]) -> None:
    client, settings = ctx
    conn = _conn(settings)
    job_id = repository.enqueue_job(conn, JobType.STT, {"recording_id": "x"})
    conn.execute("UPDATE jobs SET status = 'parked' WHERE id = ?", (job_id,))
    conn.close()

    resp = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert resp.status_code == 202

    conn = _conn(settings)
    row = conn.execute("SELECT status, attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    assert row["status"] == JobStatus.QUEUED.value
    assert row["attempts"] == 0


def test_retry_unknown_job_404(ctx: tuple[TestClient, Settings]) -> None:
    client, _ = ctx
    assert client.post("/api/v1/jobs/9999/retry").status_code == 404


def test_retry_all_jobs(ctx: tuple[TestClient, Settings]) -> None:
    client, settings = ctx
    conn = _conn(settings)
    for _ in range(3):
        jid = repository.enqueue_job(conn, JobType.STT, {"recording_id": "x"})
        conn.execute("UPDATE jobs SET status = 'parked' WHERE id = ?", (jid,))
    conn.close()

    resp = client.post("/api/v1/jobs/retry-all")
    assert resp.status_code == 202
    assert resp.json()["requeued"] == 3

    conn = _conn(settings)
    queued = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued'").fetchone()["n"]
    conn.close()
    assert queued == 3
