"""Pipeline step handlers and their registry (04 §6).

Each handler takes a claimed :class:`~loomis.models.Job` plus a context (DB
connection + settings) and performs one idempotent step, enqueuing the next.
M2 wires ``transcode? → stt → diarize → speaker_id``; ``speaker_id`` is terminal
until the summaries PR adds ``classify``.
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
from .diarize import DiarTurn, get_diarize_engine
from .models import (
    Job,
    JobType,
    RecordingStatus,
    Segment,
    TranscodePolicy,
    Transcript,
)
from .speakerid import get_embedder, match
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
        repository.enqueue_job(conn, JobType.DIARIZE, {"recording_id": rec_id})


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _label_for_segment(seg: Segment, turns: list[DiarTurn]) -> str | None:
    """Assign the diarization turn with the most temporal overlap (None if none)."""
    best_label: str | None = None
    best_overlap = 0.0
    for turn in turns:
        ov = _overlap(seg.start_s, seg.end_s, turn.start, turn.end)
        if ov > best_overlap:
            best_overlap = ov
            best_label = turn.label
    return best_label


def handle_diarize(ctx: JobContext, job: Job) -> None:
    """Label each segment with who spoke (``SPEAKER_xx``), then hand off to speaker_id (FR-5.1)."""
    conn = ctx.conn
    rec_id = _recording_id(job)
    rec = repository.get_recording(conn, rec_id)
    if rec is None or rec.library_path is None:
        raise ValueError(f"recording {rec_id} not found / has no library file")
    repository.set_recording_status(conn, rec_id, RecordingStatus.PROCESSING)

    segments = repository.get_segments_for_recording(conn, rec_id)
    engine = get_diarize_engine(ctx.settings.diarize)
    result = engine.diarize(
        Path(rec.library_path),
        min_speakers=ctx.settings.diarize.min_speakers,
        max_speakers=ctx.settings.diarize.max_speakers,
    )
    with transaction(conn):
        for seg in segments:
            if seg.id is not None:
                repository.set_segment_diar_label(
                    conn, seg.id, _label_for_segment(seg, result.turns)
                )
        repository.enqueue_job(conn, JobType.SPEAKER_ID, {"recording_id": rec_id})


def handle_speaker_id(ctx: JobContext, job: Job) -> None:
    """Resolve diarized speakers to cross-recording identities (FR-5.2–5.4).

    Embeds each diarized speaker, matches against known voiceprints (assign / new
    provisional / uncertain), writes ``segments.speaker_id``, and grows the
    voiceprint DB. Terminal until the summaries PR enqueues ``classify``.
    """
    conn = ctx.conn
    rec_id = _recording_id(job)
    rec = repository.get_recording(conn, rec_id)
    if rec is None or rec.library_path is None:
        raise ValueError(f"recording {rec_id} not found / has no library file")
    repository.set_recording_status(conn, rec_id, RecordingStatus.PROCESSING)

    segments = repository.get_segments_for_recording(conn, rec_id)
    labelled = [s for s in segments if s.diarization_label and s.id is not None]
    cfg = ctx.settings.speaker_id

    with transaction(conn):
        # Idempotent re-run: drop this recording's prior prints + any now-empty identities
        # before re-embedding, so a reclaimed job never double-counts.
        repository.delete_voiceprints_for_recording(conn, rec_id)
        repository.delete_empty_provisional_speakers(conn)

        if labelled:
            embedder = get_embedder(cfg)
            turns = [DiarTurn(s.start_s, s.end_s, s.diarization_label) for s in labelled]  # type: ignore[arg-type]
            embeddings = embedder.embed(Path(rec.library_path), turns)
            known = repository.speaker_centroids(conn)

            seg_ids_by_label: dict[str, list[int]] = {}
            for s in labelled:
                seg_ids_by_label.setdefault(s.diarization_label, []).append(s.id)  # type: ignore[arg-type]

            for label, seg_ids in seg_ids_by_label.items():
                emb = embeddings.get(label)
                if emb is None:
                    continue
                decision = match(emb, known, cfg)
                if decision.action == "new" or decision.speaker_id is None:
                    sid = repository.create_speaker(conn, needs_review=decision.needs_review)
                else:
                    sid = decision.speaker_id
                    if decision.needs_review:
                        repository.flag_speaker_review(conn, sid, True)
                repository.add_voiceprint(
                    conn, sid, emb, source_recording_id=rec_id, source_label=label
                )
                known.append((sid, emb))  # let later labels in this recording match it too
                for seg_id in seg_ids:
                    repository.set_segment_speaker(conn, seg_id, sid)

        repository.set_recording_status(conn, rec_id, RecordingStatus.DONE)


HANDLERS: dict[JobType, Handler] = {
    JobType.TRANSCODE: handle_transcode,
    JobType.STT: handle_stt,
    JobType.DIARIZE: handle_diarize,
    JobType.SPEAKER_ID: handle_speaker_id,
}
