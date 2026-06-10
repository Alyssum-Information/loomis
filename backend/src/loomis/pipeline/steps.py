"""Pipeline step handlers and their registry (04 §6).

Each handler takes a claimed :class:`~loomis.core.models.Job` plus a context (DB
connection + settings) and performs one idempotent step, enqueuing the next:
``transcode? → stt → diarize → speaker_id → classify →
{diary_aggregate | meeting_extract}``.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..cloud.sync import handle_cloud_sync
from ..core import repository
from ..core.config import Settings
from ..core.events import EventBus
from ..core.models import (
    ClassifyResult,
    DiaryDoc,
    DiaryEntry,
    Job,
    JobType,
    Meeting,
    MeetingDoc,
    RecordingKind,
    RecordingStatus,
    Segment,
    SpeakerNameGuess,
    TranscodePolicy,
    Transcript,
)
from ..core.sqlite_tx import transaction
from .classify import classify_segments
from .diarize import DiarTurn, get_diarize_engine
from .llm import LLMProvider, complete_structured, get_provider, model_id
from .speakerid import get_embedder, match
from .stt import get_engine
from .summarize import (
    PROMPT_VERSION,
    build_classify_prompt,
    build_diary_prompt,
    build_meeting_prompt,
    render_diary_markdown,
    render_meeting_markdown,
    transcript_text,
)
from .transcode import TranscodeError, Transcoder

log = logging.getLogger(__name__)


@dataclass(slots=True)
class JobContext:
    conn: sqlite3.Connection
    settings: Settings
    bus: EventBus | None = None  # present when run under the daemon; None for CLI/tests

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
    voiceprint DB, then hands off to ``classify``.
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

        repository.enqueue_job(conn, JobType.CLASSIFY, {"recording_id": rec_id})


def handle_classify(ctx: JobContext, job: Job) -> None:
    """Decide diary vs meeting, then route to the right summarizer (FR-6.1).

    Heuristics decide first; the LLM only confirms low-confidence cases when a real
    provider is configured. Diary recordings settle the day's aggregate; meetings
    get their own extraction (which then back-links into the day's diary).
    """
    conn = ctx.conn
    rec_id = _recording_id(job)
    rec = repository.get_recording(conn, rec_id)
    if rec is None:
        raise ValueError(f"recording {rec_id} not found")
    repository.set_recording_status(conn, rec_id, RecordingStatus.PROCESSING)

    segments = repository.get_segments_for_recording(conn, rec_id)
    summaries = ctx.settings.summaries
    result = classify_segments(segments, summaries)

    unsure = result.confidence < summaries.classify_confidence_floor
    if unsure and ctx.settings.llm.provider != "null":
        provider = get_provider(ctx.settings.llm)
        text = transcript_text(segments, repository.speaker_display_names(conn))
        try:
            result = complete_structured(
                provider,
                build_classify_prompt(text),
                ClassifyResult,
                max_retries=ctx.settings.llm.max_retries,
            )
        except Exception:  # noqa: BLE001 — LLM is best-effort; fall back to the heuristic
            log.warning("classify LLM confirmation failed for %s; keeping heuristic", rec_id)

    kind = RecordingKind(result.type)
    date = repository.recording_local_date(conn, rec_id)
    with transaction(conn):
        repository.set_recording_kind(conn, rec_id, kind)
        if kind == RecordingKind.MEETING:
            repository.enqueue_job(conn, JobType.MEETING_EXTRACT, {"recording_id": rec_id})
        else:
            repository.set_recording_status(conn, rec_id, RecordingStatus.DONE)
            if date:
                repository.enqueue_job(conn, JobType.DIARY_AGGREGATE, {"date": date})


# Must match the unnamed-speaker fallback in repository.speaker_display_names,
# which is what the prompts show the model (summarize.transcript_text).
_SPEAKER_LABEL_RE = re.compile(r"^Speaker (\d+)$")


def _apply_speaker_suggestions(ctx: JobContext, guesses: list[SpeakerNameGuess]) -> None:
    """Store LLM name proposals on still-unnamed speakers (FR-5.8).

    Suggestions never become display names here — the user confirms them in the
    Speakers screen. Unparseable labels and unknown ids are ignored (the model may
    hallucinate either).
    """
    for guess in guesses:
        name = guess.name.strip()
        label_match = _SPEAKER_LABEL_RE.match(guess.speaker.strip())
        if not name or label_match is None:
            continue
        speaker_id = int(label_match.group(1))
        if repository.find_speaker(ctx.conn, speaker_id) is None:
            continue
        if repository.suggest_speaker_name(ctx.conn, speaker_id, name) and ctx.bus is not None:
            ctx.bus.publish("speaker.updated", {"speaker_id": speaker_id})


def _summary_metadata(doc: DiaryDoc | MeetingDoc, provider: LLMProvider) -> dict[str, object]:
    """Summary content plus provenance (which model + prompt produced it) for reproducibility.

    Stored both in the DB ``metadata`` column and the on-disk JSON sidecar (FR-6.7).
    """
    return {
        **doc.model_dump(),
        "model": model_id(provider),
        "prompt_version": PROMPT_VERSION,
    }


def _write_sidecar(md_path: Path, markdown: str, payload: dict[str, object]) -> None:
    """Write a Markdown file plus its ``.json`` metadata sidecar (05 §1)."""
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    md_path.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def handle_meeting_extract(ctx: JobContext, job: Job) -> None:
    """Produce a standalone meeting record from a recording, then link it to the day (FR-6.3)."""
    conn = ctx.conn
    rec_id = _recording_id(job)
    rec = repository.get_recording(conn, rec_id)
    if rec is None:
        raise ValueError(f"recording {rec_id} not found")
    repository.set_recording_status(conn, rec_id, RecordingStatus.PROCESSING)

    segments = repository.get_segments_for_recording(conn, rec_id)
    text = transcript_text(segments, repository.speaker_display_names(conn))
    provider = get_provider(ctx.settings.llm)
    doc = complete_structured(
        provider,
        build_meeting_prompt(text, ctx.settings.summaries.summary_language),
        MeetingDoc,
        max_retries=ctx.settings.llm.max_retries,
    )

    date = repository.recording_local_date(conn, rec_id)
    participant_ids = sorted({s.speaker_id for s in segments if s.speaker_id is not None})
    meeting_id = uuid4().hex
    md_path = ctx.data_dir / "meetings" / f"{meeting_id}.md"
    metadata = _summary_metadata(doc, provider)
    _write_sidecar(md_path, render_meeting_markdown(doc), metadata)

    meeting = Meeting(
        id=meeting_id,
        title=doc.title or None,
        occurred_on=date,
        markdown_path=str(md_path),
        metadata=metadata,
        model=model_id(provider),
    )
    with transaction(conn):
        repository.delete_meetings_for_recording(conn, rec_id)  # idempotent re-run
        repository.insert_meeting(
            conn, meeting, recording_ids=[rec_id], participant_ids=participant_ids
        )
        _apply_speaker_suggestions(ctx, doc.speaker_names)
        repository.set_recording_status(conn, rec_id, RecordingStatus.DONE)
        if date:
            repository.enqueue_job(conn, JobType.DIARY_AGGREGATE, {"date": date})


def handle_diary_aggregate(ctx: JobContext, job: Job) -> None:
    """Write/refresh one local day's first-person diary entry + meeting links (FR-6.2, 6.6)."""
    conn = ctx.conn
    date = job.payload.get("date")
    if not isinstance(date, str):
        raise ValueError(f"diary_aggregate job {job.id} missing payload.date")

    recordings = repository.diary_recordings_for_date(conn, date)
    meetings = repository.meetings_for_date(conn, date)
    if not recordings and not meetings:
        return  # nothing settled for this day yet

    provider = get_provider(ctx.settings.llm)
    if recordings:
        names = repository.speaker_display_names(conn)
        chunks = [
            transcript_text(repository.get_segments_for_recording(conn, r.id), names)
            for r in recordings
        ]
        text = "\n\n".join(c for c in chunks if c)
        doc = complete_structured(
            provider,
            build_diary_prompt(text, ctx.settings.summaries.summary_language),
            DiaryDoc,
            max_retries=ctx.settings.llm.max_retries,
        )
    else:
        doc = DiaryDoc()  # a day with only meetings still gets an entry that links to them

    meeting_links = [(m.title or "Meeting", f"../meetings/{m.id}.md") for m in meetings]
    md_path = ctx.data_dir / "diary" / f"{date}.md"
    metadata = _summary_metadata(doc, provider)
    _write_sidecar(md_path, render_diary_markdown(date, doc, meeting_links), metadata)

    entry_id = uuid4().hex
    entry = DiaryEntry(
        id=entry_id,
        date=date,
        title=doc.title or None,
        markdown_path=str(md_path),
        metadata=metadata,
        model=model_id(provider),
    )
    with transaction(conn):
        repository.replace_diary_entry(conn, entry, [r.id for r in recordings])
        repository.link_diary_meetings(conn, entry_id, [m.id for m in meetings])
        _apply_speaker_suggestions(ctx, doc.speaker_names)

    if ctx.bus is not None:
        ctx.bus.publish("diary.updated", {"date": date})


def _payload_int(job: Job, key: str) -> int:
    value = job.payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"job {job.id} ({job.type}) missing integer payload.{key}")
    return value


def handle_speaker_merge(ctx: JobContext, job: Job) -> None:
    """Fold the source identity into the target, then delete the source (FR-5.5)."""
    conn = ctx.conn
    source_id = _payload_int(job, "source_id")
    target_id = _payload_int(job, "target_id")
    if source_id == target_id:
        return
    with transaction(conn):
        repository.reassign_speaker(conn, source_id, target_id)
        repository.delete_speaker(conn, source_id)


def handle_speaker_split(ctx: JobContext, job: Job) -> None:
    """Peel one recording off an identity into a fresh provisional speaker (FR-5.5)."""
    conn = ctx.conn
    speaker_id = _payload_int(job, "speaker_id")
    rec_id = job.payload.get("recording_id")
    if not isinstance(rec_id, str):
        raise ValueError(f"speaker_split job {job.id} missing payload.recording_id")
    with transaction(conn):
        new_id = repository.create_speaker(conn)
        repository.split_recording_to_speaker(conn, speaker_id, rec_id, new_id)


HANDLERS: dict[JobType, Handler] = {
    JobType.TRANSCODE: handle_transcode,
    JobType.STT: handle_stt,
    JobType.DIARIZE: handle_diarize,
    JobType.SPEAKER_ID: handle_speaker_id,
    JobType.CLASSIFY: handle_classify,
    JobType.MEETING_EXTRACT: handle_meeting_extract,
    JobType.DIARY_AGGREGATE: handle_diary_aggregate,
    JobType.SPEAKER_MERGE: handle_speaker_merge,
    JobType.SPEAKER_SPLIT: handle_speaker_split,
    JobType.CLOUD_SYNC: handle_cloud_sync,
}
