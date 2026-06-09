"""API response DTOs (11 §1).

Most endpoints return the domain models directly (already snake_case pydantic);
these wrappers cover pagination, search hits, and composite views. Kept separate
from ``models.py`` so the wire contract can evolve without touching storage types.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from .models import RecordingKind, RecordingStatus, Segment, Transcript


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


class StageState(StrEnum):
    """State of one pipeline stage for a file (derived from its jobs)."""

    PENDING = "pending"  # not started
    ACTIVE = "active"  # queued or running
    DONE = "done"
    FAILED = "failed"  # a job in this stage failed/parked


class PipelineStage(BaseModel):
    """One stage of a file's pipeline; ``job_id`` is the retryable job when failed."""

    state: StageState
    job_id: int | None = None
    error: str | None = None


class RecordPipeline(BaseModel):
    """A recording tracked through its processing stages: backup → STT → summary (FR-7.6).

    The Records screen renders one of these per recording. ``backup`` reflects the
    safety-spine import (no job); ``stt`` folds transcode/stt/diarize/speaker_id;
    ``summary`` folds classify/diary_aggregate/meeting_extract.
    """

    recording_id: str
    name: str  # display label — basename of the source file
    device_id: str
    device_name: str | None = None
    kind: RecordingKind | None = None
    status: RecordingStatus
    recorded_at: str | None = None
    imported_at: str | None = None
    duration_s: float | None = None
    size_bytes: int = 0
    backup: PipelineStage
    stt: PipelineStage
    summary: PipelineStage
    updated_at: str | None = None


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
