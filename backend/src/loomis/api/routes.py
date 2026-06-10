"""REST + WebSocket surface (v1) — the Vue SPA's only backend contract (11 §3–4).

Reads are plain GETs; commands either mutate quickly and return the resource, or
enqueue a durable job and return ``202`` + ``job_id`` with progress streamed over
``/ws``. Each request gets its own short-lived SQLite connection (sqlite
connections aren't shareable across the threadpool's worker threads). Errors are
normalized to ``{"error": {"code", "message"}}`` (11 §1).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from queue import Empty
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core import db, repository
from ..core.config import Settings
from ..core.events import EventBus
from ..core.models import Device, DiaryEntry, Job, JobType, Meeting, Recording, Speaker
from ..ingest import backup
from ..ingest.watcher import removable_volumes
from .schemas import (
    DeviceRegister,
    DeviceUpdate,
    JobAccepted,
    Page,
    PendingDevice,
    RecordPipeline,
    RetryResult,
    SearchHit,
    SpeakerMerge,
    SpeakerSplit,
    SpeakerUpdate,
    TimelineDay,
    TranscriptDetail,
)

router = APIRouter()

_MAX_LIMIT = 200


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """Per-request SQLite connection (opened/closed around the handler)."""
    settings: Settings = request.app.state.settings
    conn = db.connect(settings.core.resolved_data_dir / "loomis.db")
    try:
        yield conn
    finally:
        conn.close()


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Limit = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]


def _offset(cursor: str | None) -> int:
    try:
        return max(0, int(cursor)) if cursor else 0
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid cursor") from exc


def _next_cursor(offset: int, limit: int, *, has_more: bool) -> str | None:
    return str(offset + limit) if has_more else None


# --- devices (3.1) ---


@router.get("/devices", response_model=list[Device])
def list_devices(conn: Conn) -> list[Device]:
    return repository.list_devices(conn)


@router.get("/devices/pending", response_model=list[PendingDevice])
def pending_devices(conn: Conn) -> list[PendingDevice]:
    """Connected volumes that are not actively registered (the new-device prompt, FR-1.9)."""
    pending: list[PendingDevice] = []
    for vol in sorted(removable_volumes()):
        device = backup.resolve_device(conn, vol)
        if device is None or not device.registered:
            pending.append(PendingDevice(volume=str(vol)))
    return pending


@router.get("/devices/{device_id}", response_model=Device)
def get_device(device_id: str, conn: Conn) -> Device:
    device = repository.find_device(conn, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    return device


# --- recordings & transcripts (3.2) ---


@router.get("/recordings", response_model=Page[Recording])
def list_recordings(
    conn: Conn,
    limit: Limit = 50,
    cursor: str | None = None,
    device_id: str | None = None,
    status: str | None = None,
    date: str | None = None,
) -> Page[Recording]:
    offset = _offset(cursor)
    items, has_more = repository.list_recordings(
        conn, device_id=device_id, status=status, date=date, limit=limit, offset=offset
    )
    return Page(items=items, next_cursor=_next_cursor(offset, limit, has_more=has_more))


@router.get("/recordings/{recording_id}", response_model=Recording)
def get_recording(recording_id: str, conn: Conn) -> Recording:
    rec = repository.get_recording(conn, recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recording not found")
    return rec


@router.get("/recordings/{recording_id}/transcript", response_model=TranscriptDetail)
def get_transcript(recording_id: str, conn: Conn) -> TranscriptDetail:
    transcript = repository.get_transcript(conn, recording_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="transcript not found")
    segments = repository.get_segments_for_recording(conn, recording_id)
    return TranscriptDetail(transcript=transcript, segments=segments)


@router.get("/recordings/{recording_id}/audio")
def get_audio(recording_id: str, conn: Conn) -> FileResponse:
    """Stream the library audio file (FileResponse honours HTTP Range for the player)."""
    rec = repository.get_recording(conn, recording_id)
    if rec is None or rec.library_path is None:
        raise HTTPException(status_code=404, detail="audio not found")
    path = Path(rec.library_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="audio file missing")
    return FileResponse(path)


# --- timeline, diary & meetings (3.3) ---


@router.get("/timeline", response_model=list[TimelineDay])
def get_timeline(
    conn: Conn,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> list[TimelineDay]:
    return [
        TimelineDay(**row)
        for row in repository.timeline(conn, date_from=date_from, date_to=date_to)
    ]


@router.get("/diary/{date}", response_model=DiaryEntry)
def get_diary(date: str, conn: Conn) -> DiaryEntry:
    entry = repository.get_diary_entry(conn, date)
    if entry is None:
        raise HTTPException(status_code=404, detail="diary entry not found")
    return entry


@router.get("/meetings/{meeting_id}", response_model=Meeting)
def get_meeting(meeting_id: str, conn: Conn) -> Meeting:
    meeting = repository.get_meeting(conn, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    return meeting


# --- speakers, search, jobs (3.4 / 3.5) ---


@router.get("/speakers", response_model=list[Speaker])
def list_speakers(conn: Conn) -> list[Speaker]:
    return repository.list_speakers(conn)


@router.get("/search", response_model=list[SearchHit])
def search(
    conn: Conn, q: Annotated[str, Query(min_length=1)], limit: Limit = 50
) -> list[SearchHit]:
    return [SearchHit(**hit) for hit in repository.search_documents(conn, q, limit=limit)]


@router.get("/jobs", response_model=list[Job])
def list_jobs(conn: Conn, status: str | None = None, limit: Limit = 100) -> list[Job]:
    return repository.list_jobs(conn, status=status, limit=limit)


@router.get("/pipeline", response_model=Page[RecordPipeline])
def list_pipeline(conn: Conn, limit: Limit = 50, cursor: str | None = None) -> Page[RecordPipeline]:
    """Record-centric processing view (FR-7.6): one row per recording, newest first."""
    offset = _offset(cursor)
    items, has_more = repository.pipeline_rows(conn, limit=limit, offset=offset)
    return Page(items=items, next_cursor=_next_cursor(offset, limit, has_more=has_more))


# --- commands: quick writes return the resource; heavy work returns 202 + job_id ---


@router.post("/devices/register", response_model=Device, status_code=201)
def register_device(body: DeviceRegister, conn: Conn, settings: AppSettings) -> Device:
    """Register a source — connected volume or local folder (FR-1.3, FR-1.11).

    Writes device.json into the source root + the DB row. ``kind`` is auto-detected
    from the path unless given explicitly.
    """
    volume = Path(body.volume)
    if not volume.is_dir():
        raise HTTPException(status_code=404, detail="volume or folder not found")
    return backup.register_device(
        conn, volume, settings, name=body.name, auto_delete=body.auto_delete, kind=body.kind
    )


@router.delete("/devices/{device_id}", status_code=204)
def unregister_device(device_id: str, conn: Conn) -> None:
    """Unregister a device (FR-1.10): deactivate + remove device.json; recordings kept."""
    if not backup.unregister_device(conn, device_id):
        raise HTTPException(status_code=404, detail="device not found")


@router.patch("/devices/{device_id}", response_model=Device)
def update_device(device_id: str, body: DeviceUpdate, conn: Conn) -> Device:
    if repository.find_device(conn, device_id) is None:
        raise HTTPException(status_code=404, detail="device not found")
    device = repository.update_device(
        conn,
        device_id,
        name=body.name,
        auto_delete=body.auto_delete,
        transcode_policy=body.transcode_policy,
        min_free_bytes=body.min_free_bytes,
    )
    assert device is not None  # noqa: S101 (existence checked above)
    return device


@router.patch("/speakers/{speaker_id}", response_model=Speaker)
def update_speaker(speaker_id: int, body: SpeakerUpdate, conn: Conn) -> Speaker:
    if repository.find_speaker(conn, speaker_id) is None:
        raise HTTPException(status_code=404, detail="speaker not found")
    speaker = repository.update_speaker(
        conn, speaker_id, display_name=body.display_name, is_provisional=body.is_provisional
    )
    assert speaker is not None  # noqa: S101 (existence checked above)
    return speaker


@router.post("/speakers/merge", response_model=JobAccepted, status_code=202)
def merge_speakers(body: SpeakerMerge, conn: Conn) -> JobAccepted:
    for sid in (body.source_id, body.target_id):
        if repository.find_speaker(conn, sid) is None:
            raise HTTPException(status_code=404, detail=f"speaker {sid} not found")
    job_id = repository.enqueue_job(
        conn, JobType.SPEAKER_MERGE, {"source_id": body.source_id, "target_id": body.target_id}
    )
    return JobAccepted(job_id=job_id)


@router.post("/speakers/{speaker_id}/split", response_model=JobAccepted, status_code=202)
def split_speaker(speaker_id: int, body: SpeakerSplit, conn: Conn) -> JobAccepted:
    if repository.find_speaker(conn, speaker_id) is None:
        raise HTTPException(status_code=404, detail="speaker not found")
    job_id = repository.enqueue_job(
        conn, JobType.SPEAKER_SPLIT, {"speaker_id": speaker_id, "recording_id": body.recording_id}
    )
    return JobAccepted(job_id=job_id)


@router.post("/diary/{date}/resummarize", response_model=JobAccepted, status_code=202)
def resummarize_diary(date: str, conn: Conn) -> JobAccepted:
    """Re-run the day's aggregation (FR-6.8). Idempotent: it replaces the entry."""
    job_id = repository.enqueue_job(conn, JobType.DIARY_AGGREGATE, {"date": date})
    return JobAccepted(job_id=job_id)


@router.post("/jobs/{job_id}/retry", response_model=JobAccepted, status_code=202)
def retry_job(job_id: int, conn: Conn) -> JobAccepted:
    if not repository.requeue_job(conn, job_id):
        raise HTTPException(status_code=404, detail="job not found or not retryable")
    return JobAccepted(job_id=job_id)


@router.post("/jobs/retry-all", response_model=RetryResult, status_code=202)
def retry_all_jobs(conn: Conn) -> RetryResult:
    """Requeue every failed/parked job at once (FR-7.6)."""
    return RetryResult(requeued=repository.requeue_failed_jobs(conn))


@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    """Relay backend events to the SPA (11 §4): job/device/recording/diary updates.

    Subscribes to the in-process event bus and forwards each event as JSON. The bus
    queue is a (blocking, thread-safe) ``queue.Queue`` fed by the daemon's worker
    threads, so we pull it off-loop via ``to_thread`` with a short timeout; the
    timeout also lets us notice a client that has gone away.
    """
    bus: EventBus = websocket.app.state.bus
    await websocket.accept()
    queue = bus.subscribe()

    async def _watch_close() -> None:
        # Reading detects the client closing; we ignore any payload it sends.
        while True:
            await websocket.receive_text()

    closed = asyncio.create_task(_watch_close())
    try:
        while not closed.done():
            try:
                event = await asyncio.to_thread(queue.get, True, 1.0)
            except Empty:
                continue
            await websocket.send_json({"type": event.type, "data": event.data})
    except WebSocketDisconnect:
        pass
    finally:
        closed.cancel()
        bus.unsubscribe(queue)


def install_error_handlers(app: FastAPI) -> None:
    """Normalize HTTP errors to the documented ``{"error": {code, message}}`` shape."""

    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101 (registered for this type only)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.status_code, "message": exc.detail}},
        )

    app.add_exception_handler(StarletteHTTPException, handler)
