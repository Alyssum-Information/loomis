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
