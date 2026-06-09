"""API response DTOs (11 §1).

Most endpoints return the domain models directly (already snake_case pydantic);
these wrappers cover pagination, search hits, and composite views. Kept separate
from ``models.py`` so the wire contract can evolve without touching storage types.
"""

from __future__ import annotations

from pydantic import BaseModel

from .models import Segment, Transcript


class Page[T](BaseModel):
    """Cursor-paginated list envelope (11 §1). ``next_cursor`` is null on the last page."""

    items: list[T]
    next_cursor: str | None = None


class TimelineDay(BaseModel):
    date: str  # local YYYY-MM-DD
    has_diary: bool
    meeting_count: int


class SearchHit(BaseModel):
    ref_kind: str  # recording | diary | meeting
    ref_id: str
    title: str
    snippet: str


class TranscriptDetail(BaseModel):
    """A recording's transcript header plus its speaker-labelled segments (FR-7.3)."""

    transcript: Transcript
    segments: list[Segment]


class PendingDevice(BaseModel):
    """A connected volume that is not yet registered — drives the new-device prompt (FR-1.2)."""

    volume: str
    registered: bool = False


# --- command request bodies (11 §3) ---


class DeviceRegister(BaseModel):
    volume: str
    name: str | None = None
    auto_delete: bool | None = None


class DeviceUpdate(BaseModel):
    name: str | None = None
    auto_delete: bool | None = None
    transcode_policy: str | None = None
    min_free_bytes: int | None = None


class SpeakerUpdate(BaseModel):
    display_name: str | None = None
    is_provisional: bool | None = None


class SpeakerMerge(BaseModel):
    source_id: int
    target_id: int


class SpeakerSplit(BaseModel):
    recording_id: str  # the recording to peel off; the speaker is the path id


class JobAccepted(BaseModel):
    """202 response for commands that enqueue background work (11 §1)."""

    job_id: int


class RetryResult(BaseModel):
    """How many failed/parked jobs were requeued by a bulk retry."""

    requeued: int
