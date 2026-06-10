"""API response DTOs (11 §1).

Most endpoints return the domain models directly (already snake_case pydantic);
these wrappers cover pagination, search hits, and composite views. Kept separate
from ``models.py`` so the wire contract can evolve without touching storage types.
"""

from __future__ import annotations

from pydantic import BaseModel

# Pipeline read models are part of the wire contract; they live in core so the
# repository can build them without depending on the API layer.
from ..core.models import (
    DeviceKind,
    PipelineStage,
    RecordPipeline,
    Segment,
    StageState,
    Transcript,
)

__all__ = [
    "DeviceRegister",
    "DeviceUpdate",
    "JobAccepted",
    "Page",
    "PendingDevice",
    "PipelineStage",
    "RecordPipeline",
    "RetryResult",
    "SearchHit",
    "SpeakerMerge",
    "SpeakerSplit",
    "SpeakerUpdate",
    "StageState",
    "TimelineDay",
    "TranscriptDetail",
]


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
    """Register a source: a connected volume or a local folder path (FR-1.3, FR-1.11)."""

    volume: str  # volume root (e.g. "E:\\") or watched-folder path
    name: str | None = None
    auto_delete: bool | None = None
    kind: DeviceKind | None = None  # default: auto-detect (removable volume → usb, else folder)


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


class CloudRemoteOut(BaseModel):
    """One configured rclone remote, as shown in Settings (FR-8.2)."""

    name: str
    scope: list[str]
    direction: str
    dest: str


class CloudStatus(BaseModel):
    """Cloud sync state for the UI: opt-in flag, binary presence, remotes (FR-8.2)."""

    enabled: bool
    rclone_available: bool
    remotes: list[CloudRemoteOut]


class CloudSyncRequest(BaseModel):
    """Manual "sync now" (FR-8.3). ``remote`` limits the push to one remote."""

    remote: str | None = None


class RetranscribeRequest(BaseModel):
    """Bulk re-transcription filter (11 §3.2). Empty body = every transcribed recording.

    ``not_language`` is the common case: after pinning ``[stt].language``, re-run
    everything whose transcript was detected as a *different* language.
    """

    language: str | None = None  # only transcripts detected as this language
    not_language: str | None = None  # only transcripts NOT in this language


class JobAccepted(BaseModel):
    """202 response for commands that enqueue background work (11 §1)."""

    job_id: int


class RetryResult(BaseModel):
    """How many failed/parked jobs were requeued by a bulk retry."""

    requeued: int
