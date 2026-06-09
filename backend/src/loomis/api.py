"""REST read surface (v1) — the Vue SPA's query API (11 §3).

All endpoints here are read-only (GET); command endpoints that enqueue work arrive
in a later PR. Each request gets its own short-lived SQLite connection (sqlite
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

from . import db, repository
from .config import Settings
from .devicefile import device_file_path
from .events import EventBus
from .models import Device, DiaryEntry, Job, Meeting, Recording, Speaker
from .schemas import Page, PendingDevice, SearchHit, TimelineDay, TranscriptDetail
from .watcher import removable_volumes

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


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
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
    """Connected removable volumes with no registration yet (the new-device prompt)."""
    pending: list[PendingDevice] = []
    for vol in sorted(removable_volumes()):
        serial = vol.name or str(vol)
        known = device_file_path(vol).exists() or (
            repository.find_device_by_serial(conn, serial) is not None
        )
        if not known:
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
