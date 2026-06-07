"""Data-access helpers over the SQLite connection.

Thin, typed CRUD for the M1 entities (``devices``, ``recordings``, ``jobs``) so
the backup engine never writes raw SQL. The connection is opened in autocommit
mode (``db.connect``); callers wrap multi-statement units in an explicit
transaction where atomicity matters.
"""

from __future__ import annotations

import json
import sqlite3

from .models import (
    Device,
    Job,
    JobStatus,
    JobType,
    Quarantine,
    Recording,
    RecordingStatus,
    Segment,
    Transcript,
)


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
