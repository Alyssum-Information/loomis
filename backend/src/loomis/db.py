"""SQLite access + a tiny versioned migration runner.

The DB is the metadata source of truth (see ../../docs/05-data-model-and-storage.md).
Bulk content lives on the filesystem. WAL mode lets the API read while the daemon
writes. Schema is grown one numbered migration at a time; ``schema_migrations``
records what has been applied so startup is idempotent.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

# Ordered migrations: (version, SQL). Append new ones; never edit applied ones.
# Schema grows with features (../../docs/05-data-model-and-storage.md).
# 001 — M1 backup core: devices, recordings (ledger), jobs (pipeline queue).
# Later migrations add transcripts/segments/speakers/… as M2–M5 land.
_MIGRATION_001 = """
CREATE TABLE devices (
    id               TEXT PRIMARY KEY,                  -- device_id (UUID)
    name             TEXT NOT NULL,
    volume_serial    TEXT,                              -- fallback identity hint
    owner_speaker_id INTEGER,                           -- FK→speakers (added later)
    audio_globs      TEXT NOT NULL DEFAULT '[]',        -- JSON list[str]
    auto_delete      INTEGER NOT NULL DEFAULT 0,        -- bool
    transcode_policy TEXT NOT NULL DEFAULT 'keep_original',
    transcode_opts   TEXT NOT NULL DEFAULT '{}',        -- JSON
    registered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at     TEXT
);

CREATE TABLE recordings (
    id             TEXT PRIMARY KEY,                    -- UUID
    device_id      TEXT NOT NULL REFERENCES devices(id),
    source_path    TEXT NOT NULL,                       -- path on device at import
    library_path   TEXT,                                -- path in local library
    sha256         TEXT NOT NULL,                       -- dedupe key
    size_bytes     INTEGER NOT NULL,
    duration_s     REAL,
    codec          TEXT,                                -- original or 'opus'
    recorded_at    TEXT,
    imported_at    TEXT NOT NULL DEFAULT (datetime('now')),
    source_deleted INTEGER NOT NULL DEFAULT 0,          -- bool
    status         TEXT NOT NULL DEFAULT 'imported',
    UNIQUE (device_id, sha256)                          -- idempotent re-import guard
);
CREATE INDEX idx_recordings_device ON recordings (device_id);
CREATE INDEX idx_recordings_status ON recordings (status);

CREATE TABLE jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,                           -- transcode/stt/diarize/...
    payload    TEXT NOT NULL DEFAULT '{}',              -- JSON, e.g. {"recording_id": ...}
    status     TEXT NOT NULL DEFAULT 'queued',          -- queued/running/done/failed/parked
    attempts   INTEGER NOT NULL DEFAULT 0,
    worker_id  TEXT,                                    -- claimer, for crash reclaim
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_jobs_status_type ON jobs (status, type);
"""

MIGRATIONS: Sequence[tuple[int, str]] = ((1, _MIGRATION_001),)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating parents) a SQLite connection in WAL mode with FKs on."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    return int(row["v"])


def _statements(sql: str) -> list[str]:
    """Split a migration script into individual statements (no ';' inside literals)."""
    return [s.strip() for s in sql.split(";") if s.strip()]


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations, each atomically. Returns the final schema version.

    Statements are executed individually (not via ``executescript``, which would
    force an implicit commit) so the whole migration commits or rolls back as one
    — SQLite supports transactional DDL.
    """
    version = _current_version(conn)
    for target, sql in MIGRATIONS:
        if target <= version:
            continue
        conn.execute("BEGIN")
        try:
            for statement in _statements(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (target,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        version = target
    return version
