"""Pipeline step handlers and their registry (04 §6).

Each handler takes a claimed :class:`~loomis.models.Job` plus a context (DB
connection + settings) and performs one idempotent step, enqueuing the next.
M2 wires ``transcode? → stt``; ``stt`` is terminal until M3 adds ``diarize``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from . import repository
from .config import Settings
from .models import (
    Job,
    JobType,
    RecordingStatus,
    Segment,
    TranscodePolicy,
    Transcript,
)
from .sqlite_tx import transaction
from .stt import get_engine
from .transcode import TranscodeError, Transcoder

log = logging.getLogger(__name__)


@dataclass(slots=True)
class JobContext:
    conn: sqlite3.Connection
    settings: Settings

    @property
    def data_dir(self) -> Path:
        return self.settings.core.resolved_data_dir


Handler = Callable[[JobContext, Job], None]


def _recording_id(job: Job) -> str:
    rec_id = job.payload.get("recording_id")
    if not isinstance(rec_id, str):
        raise ValueError(f"job {job.id} ({job.type}) missing payload.recording_id")
    return rec_id


def handle_transcode(ctx: JobContext, job: Job) -> None:
    """Transcode the original to Opus, validate, then hand off to STT (FR-3.1–3.3)."""
    conn = ctx.conn
    rec_id = _recording_id(job)
    rec = repository.get_recording(conn, rec_id)
    if rec is None or rec.library_path is None:
        raise ValueError(f"recording {rec_id} not found / has no library file")
    repository.set_recording_status(conn, rec_id, RecordingStatus.PROCESSING)

    device = repository.find_device(conn, rec.device_id)
    policy = device.transcode_policy if device else TranscodePolicy.KEEP_ORIGINAL
    src = Path(rec.library_path)

    # Idempotency: a reclaimed/retried transcode whose recording is already Opus must
    # not re-transcode (src == dst would corrupt the only copy). Just hand off to STT.
    if policy == TranscodePolicy.KEEP_ORIGINAL or rec.codec == "opus" or src.suffix == ".opus":
        repository.enqueue_job(conn, JobType.STT, {"recording_id": rec_id})
        return

    transcoder = Transcoder(ctx.settings.transcode)
    opus = src.with_suffix(".opus")
    expected = transcoder.probe_duration(src)
    transcoder.to_opus(src, opus)
    if not transcoder.validate(opus, expected_duration=expected):
        with suppress(OSError):
            opus.unlink()
        raise TranscodeError(f"opus output failed validation for {src}")

    with transaction(conn):
        repository.set_recording_library(conn, rec_id, str(opus), "opus")
        # transcode_only deletes the original only after the Opus is validated (FR-3.3).
        if policy == TranscodePolicy.TRANSCODE_ONLY:
            with suppress(OSError):
                src.unlink()
        repository.enqueue_job(conn, JobType.STT, {"recording_id": rec_id})


def handle_stt(ctx: JobContext, job: Job) -> None:
    """Transcribe to text + time-aligned segments and persist them (FR-4.1–4.3)."""
    conn = ctx.conn
    rec_id = _recording_id(job)
    rec = repository.get_recording(conn, rec_id)
    if rec is None or rec.library_path is None:
        raise ValueError(f"recording {rec_id} not found / has no library file")
    repository.set_recording_status(conn, rec_id, RecordingStatus.PROCESSING)

    engine = get_engine(ctx.settings.stt)
    result = engine.transcribe(Path(rec.library_path), language=ctx.settings.stt.language)

    transcripts_dir = ctx.data_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    json_path = transcripts_dir / f"{rec_id}.json"
    json_path.write_text(
        json.dumps(result.to_json(engine=engine.name, model=engine.model), ensure_ascii=False),
        encoding="utf-8",
    )

    tid = uuid4().hex
    transcript = Transcript(
        id=tid,
        recording_id=rec_id,
        engine=engine.name,
        model=engine.model,
        language=result.language,
        json_path=str(json_path),
        text=result.text,
    )
    segments = [
        Segment(transcript_id=tid, idx=i, start_s=s.start, end_s=s.end, text=s.text)
        for i, s in enumerate(result.segments)
    ]
    with transaction(conn):
        repository.replace_transcript(conn, transcript, segments)
        # Terminal in M2; M3 will enqueue `diarize` here instead of marking done.
        repository.set_recording_status(conn, rec_id, RecordingStatus.DONE)


HANDLERS: dict[JobType, Handler] = {
    JobType.TRANSCODE: handle_transcode,
    JobType.STT: handle_stt,
}
