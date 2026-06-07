"""Data-access helpers over the SQLite connection.

Thin, typed CRUD for the M1 entities (``devices``, ``recordings``, ``jobs``) so
the backup engine never writes raw SQL. The connection is opened in autocommit
mode (``db.connect``); callers wrap multi-statement units in an explicit
transaction where atomicity matters.
"""

from __future__ import annotations

import json
import sqlite3

from .models import Device, JobType, Quarantine, Recording


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
