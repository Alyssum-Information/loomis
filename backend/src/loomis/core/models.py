"""Domain models + enums (pydantic).

Typed views over the SQLite rows defined in ``db.py`` / the design in
../../docs/05-data-model-and-storage.md. Only the entities the current
milestones use are modelled; more are added as features land (M2+).

JSON columns (``audio_globs``, ``transcode_opts``, job ``payload``) are exposed
as native Python types here; ``from_row`` decodes them.
"""

from __future__ import annotations

import json
import sqlite3
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field


class TranscodePolicy(StrEnum):
    KEEP_ORIGINAL = "keep_original"
    TRANSCODE_KEEP = "transcode_keep"
    TRANSCODE_ONLY = "transcode_only"


class DeviceKind(StrEnum):
    """What kind of source a ``devices`` row is (FR-1.11, ADR-0012)."""

    USB = "usb"  # removable volume; imported on connect
    FOLDER = "folder"  # watched local folder; imported by periodic poll


class RecordingStatus(StrEnum):
    IMPORTED = "imported"
    PROCESSING = "processing"
    DONE = "done"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class RecordingKind(StrEnum):
    """How a recording is summarized (set by the ``classify`` step, FR-6.1)."""

    DIARY = "diary"
    MEETING = "meeting"


class JobType(StrEnum):
    TRANSCODE = "transcode"
    STT = "stt"
    DIARIZE = "diarize"
    SPEAKER_ID = "speaker_id"
    CLASSIFY = "classify"
    DIARY_AGGREGATE = "diary_aggregate"
    MEETING_EXTRACT = "meeting_extract"
    SPEAKER_MERGE = "speaker_merge"  # user command: fold one identity into another (FR-5.5)
    SPEAKER_SPLIT = "speaker_split"  # user command: peel a recording into a new identity (FR-5.5)
    CLOUD_SYNC = "cloud_sync"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    PARKED = "parked"


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


class Device(BaseModel):
    """A registered source: a USB recorder volume or a watched folder (FR-1.11)."""

    id: str
    name: str
    kind: DeviceKind = DeviceKind.USB
    source_path: str | None = None  # folder sources: the watched folder's absolute path
    volume_serial: str | None = None
    owner_speaker_id: int | None = None
    audio_globs: list[str] = Field(default_factory=list)
    auto_delete: bool = False
    transcode_policy: TranscodePolicy = TranscodePolicy.TRANSCODE_ONLY  # ADR-0013 default
    transcode_opts: dict[str, Any] = Field(default_factory=dict)
    min_free_bytes: int = 0  # refuse to import if it would leave less free than this
    registered: bool = True  # only registered devices auto-import (FR-1.9)
    registered_at: str | None = None
    last_seen_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["audio_globs"] = _loads(d.get("audio_globs"), [])
        d["transcode_opts"] = _loads(d.get("transcode_opts"), {})
        d["auto_delete"] = bool(d.get("auto_delete", 0))
        d["registered"] = bool(d.get("registered", 1))
        return cls.model_validate(d)


class Recording(BaseModel):
    id: str
    device_id: str
    source_path: str
    library_path: str | None = None
    sha256: str
    size_bytes: int
    duration_s: float | None = None
    codec: str | None = None
    recorded_at: str | None = None
    imported_at: str | None = None
    source_deleted: bool = False
    status: RecordingStatus = RecordingStatus.IMPORTED
    kind: RecordingKind | None = None  # diary | meeting, set by classify (FR-6.1)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["source_deleted"] = bool(d.get("source_deleted", 0))
        return cls.model_validate(d)


class Job(BaseModel):
    id: int | None = None
    type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    worker_id: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["payload"] = _loads(d.get("payload"), {})
        return cls.model_validate(d)


class Transcript(BaseModel):
    """STT output header for a recording (the words/timestamps live in ``json_path``)."""

    id: str
    recording_id: str
    engine: str
    model: str | None = None
    language: str | None = None
    json_path: str | None = None
    text: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls.model_validate(dict(row))


class Segment(BaseModel):
    """One time-aligned span of a transcript; the queryable index over the JSON."""

    id: int | None = None
    transcript_id: str
    idx: int
    start_s: float
    end_s: float
    speaker_id: int | None = None  # assigned in M3 (speaker id)
    diarization_label: str | None = None  # raw label, assigned in M3
    text: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls.model_validate(dict(row))


class Speaker(BaseModel):
    """A cross-recording identity. Provisional until the user confirms/names it (FR-5.4)."""

    id: int | None = None
    display_name: str | None = None
    suggested_name: str | None = None  # LLM proposal (FR-5.8); user-confirmed into display_name
    is_provisional: bool = True
    needs_review: bool = False
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["is_provisional"] = bool(d.get("is_provisional", 1))
        d["needs_review"] = bool(d.get("needs_review", 0))
        return cls.model_validate(d)


class Voiceprint(BaseModel):
    """One L2-normalized embedding contributing to a speaker's identity (FR-5.2)."""

    id: int | None = None
    speaker_id: int
    embedding: list[float]
    dim: int
    source_recording_id: str | None = None
    source_label: str | None = None
    created_at: str | None = None


# --- summarization: LLM structured-output schemas (feature 05 §2–4) ---
# All fields default so a minimal/empty response (e.g. the null provider's "{}")
# still validates — keeps offline/CI runs working without a model.


class ClassifyResult(BaseModel):
    """Diary-vs-meeting decision for one recording (FR-6.1)."""

    type: Literal["diary", "meeting"] = "diary"
    confidence: float = 0.0
    reason: str = ""


class SpeakerNameGuess(BaseModel):
    """One LLM-inferred name for an unnamed transcript speaker (FR-5.8).

    ``speaker`` is the transcript label exactly as prompted (``Speaker <id>``);
    the pipeline maps it back to the speaker row.
    """

    speaker: str = ""
    name: str = ""


class DiaryDoc(BaseModel):
    """LLM output for a day's first-person diary entry (FR-6.2)."""

    title: str = ""
    narrative_markdown: str = ""
    topics: list[str] = Field(default_factory=list)
    mood: str = ""
    todos: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    mentioned_people: list[str] = Field(default_factory=list)
    speaker_names: list[SpeakerNameGuess] = Field(default_factory=list)


class ActionItem(BaseModel):
    owner: str = ""
    task: str = ""
    due: str | None = None


class MeetingDoc(BaseModel):
    """LLM output for a standalone meeting record (FR-6.3, FR-6.4)."""

    title: str = ""
    attendees: list[str] = Field(default_factory=list)
    summary_markdown: str = ""
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    speaker_names: list[SpeakerNameGuess] = Field(default_factory=list)


# --- summarization: persisted row models ---


class DiaryEntry(BaseModel):
    id: str
    date: str  # local YYYY-MM-DD
    title: str | None = None
    markdown_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["metadata"] = _loads(d.get("metadata"), {})
        return cls.model_validate(d)


class Meeting(BaseModel):
    id: str
    title: str | None = None
    occurred_on: str | None = None
    markdown_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["metadata"] = _loads(d.get("metadata"), {})
        return cls.model_validate(d)


# --- read models: a recording's progress through the pipeline (FR-7.6) ---


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
    safety-spine import (no job); ``stt`` covers transcript readiness (transcode/stt);
    ``summary`` folds the post-transcript work (diarize/speaker_id/classify/
    diary_aggregate/meeting_extract).
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


class CloudSyncEntry(BaseModel):
    """One push to one remote — the durable sync history (FR-8.3, 05 §4.14)."""

    id: int | None = None
    remote: str
    scope: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    result: str | None = None  # ok | error; None while running
    stats: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["scope"] = _loads(d.get("scope"), [])
        d["stats"] = _loads(d.pop("stats_json", None), {})
        return cls.model_validate(d)


class Quarantine(BaseModel):
    """A copy that failed SHA-256 verification — kept for inspection, source never deleted."""

    id: str
    device_id: str | None = None
    source_path: str
    quarantine_path: str
    reason: str = "hash_mismatch"
    size_bytes: int | None = None
    detected_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        return cls.model_validate(dict(row))
