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
