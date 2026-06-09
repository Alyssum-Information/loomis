"""Data-access helpers over the SQLite connection.

Thin, typed CRUD for the M1 entities (``devices``, ``recordings``, ``jobs``) so
the backup engine never writes raw SQL. The connection is opened in autocommit
mode (``db.connect``); callers wrap multi-statement units in an explicit
transaction where atomicity matters.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TypedDict

from .models import (
    Device,
    DiaryEntry,
    Job,
    JobStatus,
    JobType,
    Meeting,
    Quarantine,
    Recording,
    RecordingKind,
    RecordingStatus,
    Segment,
    Speaker,
    Transcript,
)
from .speakerid import Vector, blob_to_vec, centroid, vec_to_blob


class SearchRow(TypedDict):
    ref_kind: str
    ref_id: str
    title: str
    snippet: str


class TimelineRow(TypedDict):
    date: str
    has_diary: bool
    meeting_count: int


def find_device(conn: sqlite3.Connection, device_id: str) -> Device | None:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    return Device.from_row(row) if row is not None else None


def find_device_by_serial(conn: sqlite3.Connection, serial: str) -> Device | None:
    """Resolve a device by its volume-identity fallback (FR-1.5); oldest match wins."""
    if not serial:
        return None
    row = conn.execute(
        "SELECT * FROM devices WHERE volume_serial = ? ORDER BY registered_at LIMIT 1",
        (serial,),
    ).fetchone()
    return Device.from_row(row) if row is not None else None


def insert_device(conn: sqlite3.Connection, device: Device) -> None:
    conn.execute(
        """
        INSERT INTO devices
            (id, name, volume_serial, owner_speaker_id, audio_globs, auto_delete,
             transcode_policy, transcode_opts, min_free_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device.id,
            device.name,
            device.volume_serial,
            device.owner_speaker_id,
            json.dumps(device.audio_globs),
            int(device.auto_delete),
            device.transcode_policy.value,
            json.dumps(device.transcode_opts),
            device.min_free_bytes,
        ),
    )


def touch_device(conn: sqlite3.Connection, device_id: str) -> None:
    """Stamp ``last_seen_at`` to now (each connect)."""
    conn.execute("UPDATE devices SET last_seen_at = datetime('now') WHERE id = ?", (device_id,))


def recording_exists(conn: sqlite3.Connection, device_id: str, sha256: str) -> bool:
    """Authoritative dedupe: have we already imported these exact bytes?"""
    row = conn.execute(
        "SELECT 1 FROM recordings WHERE device_id = ? AND sha256 = ?",
        (device_id, sha256),
    ).fetchone()
    return row is not None


def source_already_imported(
    conn: sqlite3.Connection,
    device_id: str,
    source_path: str,
    size_bytes: int,
    recorded_at: str,
) -> bool:
    """Cheap pre-check (path + size + mtime) to skip re-hashing an unchanged file.

    Matches the design's fast pre-check (05 §4). Deliberately keyed on mtime too: a
    recorder that reuses filenames could write different content of the same size to
    the same path, and skipping on path+size alone would silently drop it. Any
    mismatch falls through to the authoritative SHA-256 + ``UNIQUE(device_id,
    sha256)`` guard, so this can only ever avoid work, never cause a missed import.
    """
    row = conn.execute(
        "SELECT 1 FROM recordings "
        "WHERE device_id = ? AND source_path = ? AND size_bytes = ? AND recorded_at = ?",
        (device_id, source_path, size_bytes, recorded_at),
    ).fetchone()
    return row is not None


def insert_recording(conn: sqlite3.Connection, rec: Recording) -> None:
    conn.execute(
        """
        INSERT INTO recordings
            (id, device_id, source_path, library_path, sha256, size_bytes,
             duration_s, codec, recorded_at, source_deleted, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rec.id,
            rec.device_id,
            rec.source_path,
            rec.library_path,
            rec.sha256,
            rec.size_bytes,
            rec.duration_s,
            rec.codec,
            rec.recorded_at,
            int(rec.source_deleted),
            rec.status.value,
        ),
    )


def mark_source_deleted(conn: sqlite3.Connection, recording_id: str) -> None:
    conn.execute("UPDATE recordings SET source_deleted = 1 WHERE id = ?", (recording_id,))


def enqueue_job(conn: sqlite3.Connection, job_type: JobType, payload: dict[str, object]) -> int:
    """Append a durable pipeline job; returns its row id."""
    cur = conn.execute(
        "INSERT INTO jobs (type, payload) VALUES (?, ?)",
        (job_type.value, json.dumps(payload)),
    )
    return int(cur.lastrowid or 0)


def insert_quarantine(conn: sqlite3.Connection, q: Quarantine) -> None:
    """Record a failed-verification copy so it is queryable, not just logged (FR-2.7)."""
    conn.execute(
        """
        INSERT INTO quarantine
            (id, device_id, source_path, quarantine_path, reason, size_bytes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (q.id, q.device_id, q.source_path, q.quarantine_path, q.reason, q.size_bytes),
    )


# --- recordings (pipeline source) ---


def get_recording(conn: sqlite3.Connection, recording_id: str) -> Recording | None:
    row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    return Recording.from_row(row) if row is not None else None


def set_recording_status(
    conn: sqlite3.Connection, recording_id: str, status: RecordingStatus
) -> None:
    conn.execute("UPDATE recordings SET status = ? WHERE id = ?", (status.value, recording_id))


def set_recording_library(
    conn: sqlite3.Connection, recording_id: str, library_path: str, codec: str | None
) -> None:
    """Point a recording at its processed library file (e.g. after transcode)."""
    conn.execute(
        "UPDATE recordings SET library_path = ?, codec = ? WHERE id = ?",
        (library_path, codec, recording_id),
    )


def set_recording_kind(conn: sqlite3.Connection, recording_id: str, kind: RecordingKind) -> None:
    """Record the diary/meeting classification of a recording (FR-6.1)."""
    conn.execute("UPDATE recordings SET kind = ? WHERE id = ?", (kind.value, recording_id))


# Local calendar day from the recording's timestamp (date portion of recorded_at,
# falling back to imported_at). Timezone-aware day boundaries are deferred.
_LOCAL_DATE = "substr(COALESCE(recorded_at, imported_at), 1, 10)"


def recording_local_date(conn: sqlite3.Connection, recording_id: str) -> str | None:
    row = conn.execute(
        f"SELECT {_LOCAL_DATE} AS d FROM recordings WHERE id = ?",  # noqa: S608
        (recording_id,),
    ).fetchone()
    return str(row["d"]) if row is not None and row["d"] is not None else None


def diary_recordings_for_date(conn: sqlite3.Connection, date: str) -> list[Recording]:
    """All diary-kind recordings on a local day, chronological (feed the daily entry)."""
    rows = conn.execute(
        "SELECT * FROM recordings "  # noqa: S608 (_LOCAL_DATE is a constant, no user input)
        f"WHERE kind = 'diary' AND {_LOCAL_DATE} = ? "
        "ORDER BY COALESCE(recorded_at, imported_at)",
        (date,),
    ).fetchall()
    return [Recording.from_row(r) for r in rows]


# --- durable job queue (04 §7) ---


def claim_job(
    conn: sqlite3.Connection,
    worker_id: str,
    *,
    lease_seconds: int,
    types: tuple[JobType, ...] | None = None,
) -> Job | None:
    """Atomically take the next runnable job, or return None.

    Runnable = ``queued``, or ``running`` whose ``updated_at`` is older than the lease
    (its worker crashed). ``BEGIN IMMEDIATE`` serialises the claim across connections so
    two workers never grab the same row. Each claim bumps ``attempts``.
    """
    type_filter = ""
    params: list[object] = [lease_seconds]
    if types:
        placeholders = ",".join("?" for _ in types)
        type_filter = f" AND type IN ({placeholders})"
        params.extend(t.value for t in types)

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM jobs "  # noqa: S608 (type_filter is built from `?` placeholders only)
            "WHERE (status = 'queued' "
            "       OR (status = 'running' "
            "           AND (julianday('now') - julianday(updated_at)) * 86400.0 > ?))"
            f"{type_filter} "
            "ORDER BY id LIMIT 1",
            params,
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', worker_id = ?, attempts = attempts + 1, "
            "updated_at = datetime('now') WHERE id = ?",
            (worker_id, row["id"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    job = Job.from_row(row)
    job.status = JobStatus.RUNNING
    job.worker_id = worker_id
    job.attempts = (job.attempts or 0) + 1
    return job


def complete_job(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'done', last_error = NULL, updated_at = datetime('now') "
        "WHERE id = ?",
        (job_id,),
    )


def fail_job(conn: sqlite3.Connection, job_id: int, error: str, *, max_attempts: int) -> JobStatus:
    """Requeue for retry, or park (dead-letter) once attempts are exhausted.

    Returns the resulting status so the caller can react (e.g. mark a recording failed).
    """
    row = conn.execute("SELECT attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
    attempts = int(row["attempts"]) if row is not None else max_attempts
    status = JobStatus.PARKED if attempts >= max_attempts else JobStatus.QUEUED
    conn.execute(
        "UPDATE jobs SET status = ?, last_error = ?, updated_at = datetime('now') WHERE id = ?",
        (status.value, error[:2000], job_id),
    )
    return status


# --- transcripts + segments (M2) ---


def replace_transcript(
    conn: sqlite3.Connection, transcript: Transcript, segments: list[Segment]
) -> None:
    """Upsert one transcript per recording (idempotent re-run): drop any prior, insert fresh.

    Segments cascade-delete with the old transcript row, so this fully replaces the
    recording's transcription.
    """
    conn.execute("DELETE FROM transcripts WHERE recording_id = ?", (transcript.recording_id,))
    conn.execute(
        """
        INSERT INTO transcripts (id, recording_id, engine, model, language, json_path, text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            transcript.id,
            transcript.recording_id,
            transcript.engine,
            transcript.model,
            transcript.language,
            transcript.json_path,
            transcript.text,
        ),
    )
    conn.executemany(
        """
        INSERT INTO segments
            (transcript_id, idx, start_s, end_s, speaker_id, diarization_label, text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                transcript.id,
                s.idx,
                s.start_s,
                s.end_s,
                s.speaker_id,
                s.diarization_label,
                s.text,
            )
            for s in segments
        ],
    )
    index_document(conn, "recording", transcript.recording_id, "", transcript.text or "")


# --- full-text search index (FR-7.5); maintained here, not via DB triggers ---


def index_document(
    conn: sqlite3.Connection, ref_kind: str, ref_id: str, title: str, body: str
) -> None:
    """Upsert one searchable document (delete any prior row for this ref, then insert)."""
    conn.execute("DELETE FROM search_fts WHERE ref_kind = ? AND ref_id = ?", (ref_kind, ref_id))
    conn.execute(
        "INSERT INTO search_fts (ref_kind, ref_id, title, body) VALUES (?, ?, ?, ?)",
        (ref_kind, ref_id, title or "", body or ""),
    )


def unindex_document(conn: sqlite3.Connection, ref_kind: str, ref_id: str) -> None:
    conn.execute("DELETE FROM search_fts WHERE ref_kind = ? AND ref_id = ?", (ref_kind, ref_id))


def search_documents(conn: sqlite3.Connection, query: str, *, limit: int) -> list[SearchRow]:
    """Full-text search across transcripts/diaries/meetings, best match first (FR-7.5).

    The query is wrapped as an FTS5 phrase so arbitrary user input can't trip the
    FTS query grammar.
    """
    phrase = '"' + query.replace('"', '""') + '"'
    rows = conn.execute(
        "SELECT ref_kind, ref_id, title, "
        "snippet(search_fts, -1, '[', ']', '…', 12) AS snippet "
        "FROM search_fts WHERE search_fts MATCH ? ORDER BY rank LIMIT ?",
        (phrase, limit),
    ).fetchall()
    return [
        SearchRow(
            ref_kind=str(r["ref_kind"]),
            ref_id=str(r["ref_id"]),
            title=str(r["title"]),
            snippet=str(r["snippet"]),
        )
        for r in rows
    ]


# --- segments (diarization + speaker id) ---


def get_segments_for_recording(conn: sqlite3.Connection, recording_id: str) -> list[Segment]:
    """All segments of a recording's transcript, in order (for diarize / speaker_id)."""
    rows = conn.execute(
        "SELECT s.* FROM segments s "
        "JOIN transcripts t ON s.transcript_id = t.id "
        "WHERE t.recording_id = ? ORDER BY s.idx",
        (recording_id,),
    ).fetchall()
    return [Segment.from_row(r) for r in rows]


def set_segment_diar_label(conn: sqlite3.Connection, segment_id: int, label: str | None) -> None:
    conn.execute("UPDATE segments SET diarization_label = ? WHERE id = ?", (label, segment_id))


def set_segment_speaker(conn: sqlite3.Connection, segment_id: int, speaker_id: int) -> None:
    conn.execute("UPDATE segments SET speaker_id = ? WHERE id = ?", (speaker_id, segment_id))


# --- speakers + voiceprints (cross-recording identity, FR-5.2–5.4) ---


def create_speaker(conn: sqlite3.Connection, *, needs_review: bool = False) -> int:
    """Create a provisional, unnamed identity; returns its id."""
    cur = conn.execute(
        "INSERT INTO speakers (is_provisional, needs_review) VALUES (1, ?)",
        (int(needs_review),),
    )
    return int(cur.lastrowid or 0)


def find_speaker(conn: sqlite3.Connection, speaker_id: int) -> Speaker | None:
    row = conn.execute("SELECT * FROM speakers WHERE id = ?", (speaker_id,)).fetchone()
    return Speaker.from_row(row) if row is not None else None


def flag_speaker_review(conn: sqlite3.Connection, speaker_id: int, needs_review: bool) -> None:
    conn.execute(
        "UPDATE speakers SET needs_review = ?, updated_at = datetime('now') WHERE id = ?",
        (int(needs_review), speaker_id),
    )


def add_voiceprint(
    conn: sqlite3.Connection,
    speaker_id: int,
    embedding: Vector,
    *,
    source_recording_id: str | None = None,
    source_label: str | None = None,
) -> None:
    """Append an embedding to a speaker's identity (the accuracy flywheel, FR-5.2)."""
    conn.execute(
        """
        INSERT INTO voiceprints
            (speaker_id, embedding, dim, source_recording_id, source_label)
        VALUES (?, ?, ?, ?, ?)
        """,
        (speaker_id, vec_to_blob(embedding), len(embedding), source_recording_id, source_label),
    )


def delete_voiceprints_for_recording(conn: sqlite3.Connection, recording_id: str) -> None:
    """Drop this recording's contributions so a re-run of speaker_id is idempotent."""
    conn.execute("DELETE FROM voiceprints WHERE source_recording_id = ?", (recording_id,))


def delete_empty_provisional_speakers(conn: sqlite3.Connection) -> None:
    """Remove auto-created identities left with no voiceprints (e.g. after a re-run)."""
    conn.execute(
        "DELETE FROM speakers WHERE is_provisional = 1 "
        "AND id NOT IN (SELECT DISTINCT speaker_id FROM voiceprints)"
    )


def speaker_centroids(conn: sqlite3.Connection) -> list[tuple[int, Vector]]:
    """One L2-normalized centroid per speaker — the in-memory match index (§5, §8)."""
    rows = conn.execute(
        "SELECT speaker_id, embedding FROM voiceprints ORDER BY speaker_id"
    ).fetchall()
    by_speaker: dict[int, list[Vector]] = {}
    for r in rows:
        by_speaker.setdefault(int(r["speaker_id"]), []).append(blob_to_vec(r["embedding"]))
    return [(sid, centroid(vecs)) for sid, vecs in by_speaker.items()]


def speaker_display_names(conn: sqlite3.Connection) -> dict[int, str]:
    """Map speaker id → a human name, falling back to ``Speaker <id>`` for unnamed ones."""
    rows = conn.execute("SELECT id, display_name FROM speakers").fetchall()
    return {int(r["id"]): (r["display_name"] or f"Speaker {r['id']}") for r in rows}


# --- diary + meeting summaries (FR-6.2–6.6) ---


def replace_diary_entry(
    conn: sqlite3.Connection, entry: DiaryEntry, recording_ids: list[str]
) -> None:
    """Upsert one entry per local day (idempotent re-summary): drop prior, insert fresh.

    ``diary_recordings`` and ``diary_meeting_links`` cascade-delete with the old row.
    """
    conn.execute("DELETE FROM diary_entries WHERE date = ?", (entry.date,))
    conn.execute(
        """
        INSERT INTO diary_entries (id, date, title, markdown_path, metadata, model)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            entry.id,
            entry.date,
            entry.title,
            entry.markdown_path,
            json.dumps(entry.metadata, ensure_ascii=False),
            entry.model,
        ),
    )
    conn.executemany(
        "INSERT INTO diary_recordings (diary_entry_id, recording_id) VALUES (?, ?)",
        [(entry.id, rid) for rid in recording_ids],
    )
    index_document(
        conn,
        "diary",
        entry.date,
        entry.title or "",
        str(entry.metadata.get("narrative_markdown", "")),
    )


def link_diary_meetings(
    conn: sqlite3.Connection, diary_entry_id: str, meeting_ids: list[str]
) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO diary_meeting_links (diary_entry_id, meeting_id) VALUES (?, ?)",
        [(diary_entry_id, mid) for mid in meeting_ids],
    )


def meetings_for_date(conn: sqlite3.Connection, date: str) -> list[Meeting]:
    rows = conn.execute(
        "SELECT * FROM meetings WHERE occurred_on = ? ORDER BY created_at", (date,)
    ).fetchall()
    return [Meeting.from_row(r) for r in rows]


def delete_meetings_for_recording(conn: sqlite3.Connection, recording_id: str) -> None:
    """Drop any meeting built from this recording so meeting_extract is idempotent."""
    ids = [
        str(r["meeting_id"])
        for r in conn.execute(
            "SELECT meeting_id FROM meeting_recordings WHERE recording_id = ?", (recording_id,)
        ).fetchall()
    ]
    for mid in ids:
        unindex_document(conn, "meeting", mid)
    conn.execute(
        "DELETE FROM meetings WHERE id IN "
        "(SELECT meeting_id FROM meeting_recordings WHERE recording_id = ?)",
        (recording_id,),
    )


def insert_meeting(
    conn: sqlite3.Connection,
    meeting: Meeting,
    *,
    recording_ids: list[str],
    participant_ids: list[int],
) -> None:
    conn.execute(
        """
        INSERT INTO meetings (id, title, occurred_on, markdown_path, metadata, model)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            meeting.id,
            meeting.title,
            meeting.occurred_on,
            meeting.markdown_path,
            json.dumps(meeting.metadata, ensure_ascii=False),
            meeting.model,
        ),
    )
    conn.executemany(
        "INSERT INTO meeting_recordings (meeting_id, recording_id) VALUES (?, ?)",
        [(meeting.id, rid) for rid in recording_ids],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO meeting_participants (meeting_id, speaker_id) VALUES (?, ?)",
        [(meeting.id, sid) for sid in participant_ids],
    )
    index_document(
        conn,
        "meeting",
        meeting.id,
        meeting.title or "",
        str(meeting.metadata.get("summary_markdown", "")),
    )


# --- API read queries (M3 REST surface) ---


def list_devices(conn: sqlite3.Connection) -> list[Device]:
    rows = conn.execute("SELECT * FROM devices ORDER BY registered_at").fetchall()
    return [Device.from_row(r) for r in rows]


def list_recordings(
    conn: sqlite3.Connection,
    *,
    device_id: str | None = None,
    status: str | None = None,
    date: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Recording], bool]:
    """Filtered, newest-first recordings page. Returns ``(items, has_more)``."""
    clauses: list[str] = []
    params: list[object] = []
    if device_id:
        clauses.append("device_id = ?")
        params.append(device_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if date:
        clauses.append(f"{_LOCAL_DATE} = ?")
        params.append(date)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM recordings{where} "  # noqa: S608 (clauses use ? placeholders only)
        "ORDER BY COALESCE(recorded_at, imported_at) DESC, id DESC LIMIT ? OFFSET ?",
        (*params, limit + 1, offset),
    ).fetchall()
    has_more = len(rows) > limit
    return [Recording.from_row(r) for r in rows[:limit]], has_more


def get_transcript(conn: sqlite3.Connection, recording_id: str) -> Transcript | None:
    row = conn.execute(
        "SELECT * FROM transcripts WHERE recording_id = ?", (recording_id,)
    ).fetchone()
    return Transcript.from_row(row) if row is not None else None


def list_speakers(conn: sqlite3.Connection) -> list[Speaker]:
    rows = conn.execute("SELECT * FROM speakers ORDER BY id").fetchall()
    return [Speaker.from_row(r) for r in rows]


def get_diary_entry(conn: sqlite3.Connection, date: str) -> DiaryEntry | None:
    row = conn.execute("SELECT * FROM diary_entries WHERE date = ?", (date,)).fetchone()
    return DiaryEntry.from_row(row) if row is not None else None


def get_meeting(conn: sqlite3.Connection, meeting_id: str) -> Meeting | None:
    row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    return Meeting.from_row(row) if row is not None else None


def list_jobs(conn: sqlite3.Connection, *, status: str | None = None, limit: int) -> list[Job]:
    if status:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [Job.from_row(r) for r in rows]


def timeline(
    conn: sqlite3.Connection, *, date_from: str | None = None, date_to: str | None = None
) -> list[TimelineRow]:
    """Days that have a diary entry and/or meetings, with per-day meeting counts (FR-7.2)."""
    clauses: list[str] = []
    params: list[object] = []
    if date_from:
        clauses.append("d >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("d <= ?")
        params.append(date_to)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        "SELECT d AS date, MAX(has_diary) AS has_diary, SUM(meeting_count) AS meeting_count "  # noqa: S608
        "FROM ("
        "  SELECT date AS d, 1 AS has_diary, 0 AS meeting_count FROM diary_entries"
        "  UNION ALL"
        "  SELECT occurred_on AS d, 0, 1 FROM meetings WHERE occurred_on IS NOT NULL"
        f") {where} GROUP BY d ORDER BY d DESC",
        params,
    ).fetchall()
    return [
        TimelineRow(
            date=str(r["date"]),
            has_diary=bool(r["has_diary"]),
            meeting_count=int(r["meeting_count"]),
        )
        for r in rows
    ]
