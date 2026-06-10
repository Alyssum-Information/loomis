"""Speaker matching unit logic + diarize/speaker_id pipeline integration (null engines)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loomis.core import db, repository
from loomis.core.config import (
    BackupSettings,
    CoreSettings,
    DiarizeSettings,
    LlmSettings,
    Settings,
    SpeakerIdSettings,
    SttSettings,
)
from loomis.core.models import Device, JobType, Recording, RecordingStatus, Segment, Transcript
from loomis.core.vectors import blob_to_vec, centroid, cosine, vec_to_blob
from loomis.pipeline.runner import JobRunner
from loomis.pipeline.speakerid import MatchDecision, match

# --- vector math ---


def test_blob_roundtrip_preserves_vector() -> None:
    vec = (0.1, -0.2, 0.3, 0.4)
    back = blob_to_vec(vec_to_blob(vec))
    assert len(back) == len(vec)
    assert all(abs(a - b) < 1e-6 for a, b in zip(back, vec, strict=True))


def test_cosine_and_centroid() -> None:
    assert abs(cosine((1.0, 0.0), (1.0, 0.0)) - 1.0) < 1e-9
    assert abs(cosine((1.0, 0.0), (0.0, 1.0))) < 1e-9
    assert cosine((0.0, 0.0), (1.0, 0.0)) == 0.0  # zero-guard
    c = centroid([(1.0, 0.0), (0.0, 1.0)])
    assert abs(math_norm(c) - 1.0) < 1e-6  # centroid is L2-normalized


def math_norm(v: tuple[float, ...]) -> float:
    return float(sum(x * x for x in v) ** 0.5)


# --- matching decision (FR-5.3, FR-5.4) ---

_CFG = SpeakerIdSettings()


def test_match_no_known_creates_new() -> None:
    d = match((1.0, 0.0, 0.0), [], _CFG)
    assert d == MatchDecision(action="new", speaker_id=None, needs_review=False)


def test_match_strong_assigns_existing() -> None:
    d = match((1.0, 0.0, 0.0), [(7, (1.0, 0.0, 0.0))], _CFG)
    assert d.action == "assign"
    assert d.speaker_id == 7
    assert d.needs_review is False


def test_match_far_creates_new() -> None:
    d = match((1.0, 0.0, 0.0), [(7, (0.0, 1.0, 0.0))], _CFG)
    assert d.action == "new"  # cosine 0 < new_identity_below


def test_match_borderline_is_uncertain() -> None:
    # cosine 0.6 → between new_identity_below (0.55) and match_threshold (0.70).
    d = match((1.0, 0.0, 0.0), [(7, (0.6, 0.8, 0.0))], _CFG)
    assert d.action == "uncertain"
    assert d.speaker_id == 7
    assert d.needs_review is True


# --- pipeline integration: diarize → speaker_id ---


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        # tmp_path sources look like folders; skip the sync settle window in tests
        backup=BackupSettings(folder_settle_seconds=0.0),
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


def _seed_recording(conn: sqlite3.Connection, rec_id: str, *, sha: str) -> None:
    """Insert a device (once), a recording, and a 2-segment transcript ready to diarize."""
    if repository.find_device(conn, "dev-1") is None:
        repository.insert_device(conn, Device(id="dev-1", name="Recorder"))
    repository.insert_recording(
        conn,
        Recording(
            id=rec_id,
            device_id="dev-1",
            source_path=f"{rec_id}.wav",
            library_path=f"{rec_id}.wav",  # null engines don't open it
            sha256=sha,
            size_bytes=1,
            status=RecordingStatus.IMPORTED,
        ),
    )
    tid = f"t-{rec_id}"
    transcript = Transcript(id=tid, recording_id=rec_id, engine="null")
    segments = [
        Segment(transcript_id=tid, idx=0, start_s=0.0, end_s=1.0, text="hello"),
        Segment(transcript_id=tid, idx=1, start_s=1.0, end_s=2.0, text="there"),
    ]
    repository.replace_transcript(conn, transcript, segments)


def test_diarize_then_speaker_id_assigns_identity(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1", sha="h1")
    repository.enqueue_job(conn, JobType.DIARIZE, {"recording_id": "rec-1"})

    processed = JobRunner(settings).drain(conn)
    assert processed == 4  # diarize → speaker_id → classify → diary_aggregate

    segs = repository.get_segments_for_recording(conn, "rec-1")
    assert all(s.diarization_label == "SPEAKER_00" for s in segs)
    assert all(s.speaker_id is not None for s in segs)
    assert len({s.speaker_id for s in segs}) == 1  # both turns → one identity

    assert conn.execute("SELECT COUNT(*) AS n FROM speakers").fetchone()["n"] == 1
    vp = conn.execute("SELECT * FROM voiceprints").fetchall()
    assert len(vp) == 1
    assert vp[0]["source_recording_id"] == "rec-1"
    assert conn.execute("SELECT status FROM recordings").fetchone()["status"] == "done"


def test_speaker_id_rerun_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1", sha="h1")
    repository.enqueue_job(conn, JobType.DIARIZE, {"recording_id": "rec-1"})
    JobRunner(settings).drain(conn)

    # Re-run only speaker_id (e.g. a reclaimed job): must not double-count.
    repository.enqueue_job(conn, JobType.SPEAKER_ID, {"recording_id": "rec-1"})
    JobRunner(settings).drain(conn)

    assert conn.execute("SELECT COUNT(*) AS n FROM speakers").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM voiceprints").fetchone()["n"] == 1


def test_same_voice_matches_across_recordings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1", sha="h1")
    _seed_recording(conn, "rec-2", sha="h2")
    repository.enqueue_job(conn, JobType.DIARIZE, {"recording_id": "rec-1"})
    repository.enqueue_job(conn, JobType.DIARIZE, {"recording_id": "rec-2"})

    JobRunner(settings).drain(conn)

    # Null embedder gives the same vector for SPEAKER_00 → one shared identity,
    # two voiceprints (one contributed per recording).
    assert conn.execute("SELECT COUNT(*) AS n FROM speakers").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM voiceprints").fetchone()["n"] == 2
    s1 = repository.get_segments_for_recording(conn, "rec-1")[0].speaker_id
    s2 = repository.get_segments_for_recording(conn, "rec-2")[0].speaker_id
    assert s1 == s2
