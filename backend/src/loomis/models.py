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
from typing import Any, Self

from pydantic import BaseModel, Field


class TranscodePolicy(StrEnum):
    KEEP_ORIGINAL = "keep_original"
    TRANSCODE_KEEP = "transcode_keep"
    TRANSCODE_ONLY = "transcode_only"


class RecordingStatus(StrEnum):
    IMPORTED = "imported"
    PROCESSING = "processing"
    DONE = "done"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class JobType(StrEnum):
    TRANSCODE = "transcode"
    STT = "stt"
    DIARIZE = "diarize"
    SPEAKER_ID = "speaker_id"
    CLASSIFY = "classify"
    DIARY_AGGREGATE = "diary_aggregate"
    MEETING_EXTRACT = "meeting_extract"
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
    id: str
    name: str
    volume_serial: str | None = None
    owner_speaker_id: int | None = None
    audio_globs: list[str] = Field(default_factory=list)
    auto_delete: bool = False
    transcode_policy: TranscodePolicy = TranscodePolicy.KEEP_ORIGINAL
    transcode_opts: dict[str, Any] = Field(default_factory=dict)
    min_free_bytes: int = 0  # refuse to import if it would leave less free than this
    registered_at: str | None = None
    last_seen_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        d = dict(row)
        d["audio_globs"] = _loads(d.get("audio_globs"), [])
        d["transcode_opts"] = _loads(d.get("transcode_opts"), {})
        d["auto_delete"] = bool(d.get("auto_delete", 0))
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
