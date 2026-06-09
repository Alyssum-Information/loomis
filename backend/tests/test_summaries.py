"""Classification heuristics, structured-output plumbing, and the summary pipeline."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loomis import db, repository
from loomis.classify import classify_segments
from loomis.config import (
    CoreSettings,
    DiarizeSettings,
    LlmSettings,
    Settings,
    SpeakerIdSettings,
    SttSettings,
    SummariesSettings,
)
from loomis.jobs import JobRunner
from loomis.llm import NullProvider, complete_structured, get_provider, model_id
from loomis.models import (
    Device,
    DiaryDoc,
    JobType,
    Recording,
    RecordingStatus,
    Segment,
    Transcript,
)

_SUM = SummariesSettings()


# --- classification heuristics (FR-6.1) ---


def _seg(idx: int, start: float, end: float, speaker_id: int) -> Segment:
    return Segment(
        transcript_id="t", idx=idx, start_s=start, end_s=end, speaker_id=speaker_id, text="x"
    )


def test_single_speaker_is_diary() -> None:
    r = classify_segments([_seg(0, 0, 5, 1), _seg(1, 5, 9, 1)], _SUM)
    assert r.type == "diary"
    assert r.confidence >= 0.6


def test_two_balanced_speakers_is_meeting() -> None:
    r = classify_segments([_seg(0, 0, 5, 1), _seg(1, 5, 10, 2)], _SUM)
    assert r.type == "meeting"


def test_owner_dominant_multispeaker_is_diary() -> None:
    # Speaker 1 dominates; speaker 2 is a brief interjection → still a diary day.
    r = classify_segments([_seg(0, 0, 95, 1), _seg(1, 95, 100, 2)], _SUM)
    assert r.type == "diary"


def test_no_segments_uses_bias() -> None:
    assert classify_segments([], _SUM).type == "diary"


# --- structured output ---


def test_null_provider_yields_defaulted_doc() -> None:
    doc = complete_structured(NullProvider(), "irrelevant", DiaryDoc, max_retries=0)
    assert isinstance(doc, DiaryDoc)
    assert doc.narrative_markdown == ""
    assert doc.topics == []


def test_model_id_format() -> None:
    assert model_id(NullProvider()) == "null"


# --- pipeline integration: classify → meeting_extract → diary_aggregate ---


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        stt=SttSettings(engine="null"),
        diarize=DiarizeSettings(engine="null"),
        speaker_id=SpeakerIdSettings(engine="null"),
        llm=LlmSettings(provider="null"),
    )


def _conn(settings: Settings) -> sqlite3.Connection:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    c = db.connect(data_dir / "loomis.db")
    db.apply_migrations(c)
    return c


def _seed_meeting(conn: sqlite3.Connection, rec_id: str, date_iso: str) -> None:
    """A two-speaker recording with balanced talk time → classifies as a meeting."""
    repository.insert_device(conn, Device(id="dev-1", name="Recorder"))
    s1 = repository.create_speaker(conn)
    s2 = repository.create_speaker(conn)
    repository.insert_recording(
        conn,
        Recording(
            id=rec_id,
            device_id="dev-1",
            source_path=f"{rec_id}.wav",
            library_path=f"{rec_id}.wav",
            sha256="h1",
            size_bytes=1,
            recorded_at=date_iso,
            status=RecordingStatus.IMPORTED,
        ),
    )
    tid = f"t-{rec_id}"
    transcript = Transcript(id=tid, recording_id=rec_id, engine="null")
    segments = [
        Segment(transcript_id=tid, idx=0, start_s=0.0, end_s=5.0, speaker_id=s1, text="hi"),
        Segment(transcript_id=tid, idx=1, start_s=5.0, end_s=10.0, speaker_id=s2, text="hey"),
    ]
    repository.replace_transcript(conn, transcript, segments)
    # diarization labels exist on real runs; not needed once speaker_id is set.


def test_meeting_flow_creates_record_and_diary_link(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_meeting(conn, "rec-1", "2026-06-09T10:00:00+08:00")
    repository.enqueue_job(conn, JobType.CLASSIFY, {"recording_id": "rec-1"})

    processed = JobRunner(settings).drain(conn)
    assert processed == 3  # classify → meeting_extract → diary_aggregate

    assert conn.execute("SELECT kind FROM recordings").fetchone()["kind"] == "meeting"
    assert conn.execute("SELECT status FROM recordings").fetchone()["status"] == "done"

    assert conn.execute("SELECT COUNT(*) AS n FROM meetings").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM meeting_recordings").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM meeting_participants").fetchone()["n"] == 2

    diary = conn.execute("SELECT * FROM diary_entries").fetchone()
    assert diary is not None
    assert diary["date"] == "2026-06-09"
    assert conn.execute("SELECT COUNT(*) AS n FROM diary_meeting_links").fetchone()["n"] == 1

    assert (settings.core.resolved_data_dir / "diary" / "2026-06-09.md").is_file()
    meeting_id = conn.execute("SELECT id FROM meetings").fetchone()["id"]
    assert (settings.core.resolved_data_dir / "meetings" / f"{meeting_id}.md").is_file()


def test_meeting_extract_rerun_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_meeting(conn, "rec-1", "2026-06-09T10:00:00+08:00")
    repository.enqueue_job(conn, JobType.CLASSIFY, {"recording_id": "rec-1"})
    JobRunner(settings).drain(conn)

    repository.enqueue_job(conn, JobType.MEETING_EXTRACT, {"recording_id": "rec-1"})
    JobRunner(settings).drain(conn)

    assert conn.execute("SELECT COUNT(*) AS n FROM meetings").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM diary_entries").fetchone()["n"] == 1


def test_get_provider_unknown_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown llm provider"):
        get_provider(LlmSettings(provider="bogus"))
