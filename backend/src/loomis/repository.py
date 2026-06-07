"""Data-access helpers over the SQLite connection.

Thin, typed CRUD for the M1 entities (``devices``, ``recordings``, ``jobs``) so
the backup engine never writes raw SQL. The connection is opened in autocommit
mode (``db.connect``); callers wrap multi-statement units in an explicit
transaction where atomicity matters.
"""

from __future__ import annotations

import json
import sqlite3

from .models import Device, JobType, Recording


def find_device(conn: sqlite3.Connection, device_id: str) -> Device | None:
    row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    return Device.from_row(row) if row is not None else None


def insert_device(conn: sqlite3.Connection, device: Device) -> None:
    conn.execute(
        """
        INSERT INTO devices
            (id, name, volume_serial, owner_speaker_id, audio_globs, auto_delete,
             transcode_policy, transcode_opts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
    conn: sqlite3.Connection, device_id: str, source_path: str, size_bytes: int
) -> bool:
    """Cheap pre-check (path + size) to skip re-hashing an unchanged source file.

    Not authoritative — SHA-256 + the ``UNIQUE(device_id, sha256)`` guard are. This
    only avoids the hashing cost for files we have demonstrably already seen.
    """
    row = conn.execute(
        "SELECT 1 FROM recordings WHERE device_id = ? AND source_path = ? AND size_bytes = ?",
        (device_id, source_path, size_bytes),
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
