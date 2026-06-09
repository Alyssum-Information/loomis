"""Record-centric pipeline view (FR-7.6): per-recording backup → STT → summary stages."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loomis import db, repository
from loomis.models import Device, JobStatus, JobType, Recording, RecordingStatus
from loomis.schemas import RecordPipeline, StageState


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "loomis.db")
    db.apply_migrations(c)
    repository.insert_device(c, Device(id="dev1", name="Recorder"))
    return c


def _add_recording(
    conn: sqlite3.Connection,
    rec_id: str,
    *,
    source_path: str = "/recorder/AUDIO/clip.wav",
    status: RecordingStatus = RecordingStatus.IMPORTED,
) -> None:
    repository.insert_recording(
        conn,
        Recording(
            id=rec_id,
            device_id="dev1",
            source_path=source_path,
            library_path=f"/lib/{rec_id}.wav",
            sha256=rec_id.ljust(64, "0"),
            size_bytes=1,
            status=status,
        ),
    )


def _set_status(conn: sqlite3.Connection, job_id: int, status: JobStatus, error: str = "") -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, last_error = ? WHERE id = ?",
        (status.value, error or None, job_id),
    )


def _only(conn: sqlite3.Connection) -> RecordPipeline:
    rows, has_more = repository.pipeline_rows(conn, limit=50, offset=0)
    assert not has_more
    assert len(rows) == 1
    return rows[0]


def test_imported_no_jobs_backup_done_rest_pending(conn: sqlite3.Connection) -> None:
    _add_recording(conn, "r1")
    row = _only(conn)
    assert row.name == "clip.wav"
    assert row.backup.state == StageState.DONE
    assert row.stt.state == StageState.PENDING
    assert row.summary.state == StageState.PENDING


def test_stt_queued_is_active(conn: sqlite3.Connection) -> None:
    _add_recording(conn, "r1")
    repository.enqueue_job(conn, JobType.STT, {"recording_id": "r1"})
    row = _only(conn)
    assert row.stt.state == StageState.ACTIVE
    assert row.summary.state == StageState.PENDING


def test_stt_done_summary_active(conn: sqlite3.Connection) -> None:
    _add_recording(conn, "r1")
    stt = repository.enqueue_job(conn, JobType.STT, {"recording_id": "r1"})
    _set_status(conn, stt, JobStatus.DONE)
    repository.enqueue_job(conn, JobType.CLASSIFY, {"recording_id": "r1"})
    row = _only(conn)
    assert row.stt.state == StageState.DONE
    assert row.summary.state == StageState.ACTIVE


def test_parked_stt_surfaces_failed_with_retry_job(conn: sqlite3.Connection) -> None:
    _add_recording(conn, "r1")
    stt = repository.enqueue_job(conn, JobType.STT, {"recording_id": "r1"})
    _set_status(conn, stt, JobStatus.PARKED, "No module named 'whisperx'")
    row = _only(conn)
    assert row.stt.state == StageState.FAILED
    assert row.stt.job_id == stt
    assert row.stt.error == "No module named 'whisperx'"


def test_quarantined_recording_backup_failed(conn: sqlite3.Connection) -> None:
    _add_recording(conn, "r1", status=RecordingStatus.QUARANTINED)
    row = _only(conn)
    assert row.backup.state == StageState.FAILED


def test_multiple_stt_types_bucketed_together(conn: sqlite3.Connection) -> None:
    _add_recording(conn, "r1")
    tc = repository.enqueue_job(conn, JobType.TRANSCODE, {"recording_id": "r1"})
    _set_status(conn, tc, JobStatus.DONE)
    diar = repository.enqueue_job(conn, JobType.DIARIZE, {"recording_id": "r1"})
    _set_status(conn, diar, JobStatus.RUNNING)
    row = _only(conn)
    # transcode done but diarize running → STT stage still active (not done)
    assert row.stt.state == StageState.ACTIVE


def test_done_recording_all_stages_done_without_jobs(conn: sqlite3.Connection) -> None:
    _add_recording(conn, "r1", status=RecordingStatus.DONE)
    row = _only(conn)
    assert row.backup.state == StageState.DONE
    assert row.stt.state == StageState.DONE
    assert row.summary.state == StageState.DONE


def test_pagination_reports_has_more(conn: sqlite3.Connection) -> None:
    for i in range(3):
        _add_recording(conn, f"r{i}")
    rows, has_more = repository.pipeline_rows(conn, limit=2, offset=0)
    assert len(rows) == 2
    assert has_more
