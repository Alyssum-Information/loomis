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

# 002 — M1 hardening: a local free-space guard per device, and a durable record of
# copies that failed verification (so quarantine events are queryable, not just logged).
_MIGRATION_002 = """
ALTER TABLE devices ADD COLUMN min_free_bytes INTEGER NOT NULL DEFAULT 0;

CREATE TABLE quarantine (
    id              TEXT PRIMARY KEY,                    -- UUID
    device_id       TEXT REFERENCES devices(id),
    source_path     TEXT NOT NULL,                       -- file on the device
    quarantine_path TEXT NOT NULL,                       -- where the bad copy was parked
    reason          TEXT NOT NULL,                       -- e.g. 'hash_mismatch'
    size_bytes      INTEGER,
    detected_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_quarantine_device ON quarantine (device_id);
"""

# 003 — M2 transcription: one transcript per recording (UNIQUE → idempotent re-run)
# plus its time-aligned, speaker-labelled segment index (05 §4.3–4.4).
_MIGRATION_003 = """
CREATE TABLE transcripts (
    id           TEXT PRIMARY KEY,                       -- UUID
    recording_id TEXT NOT NULL UNIQUE REFERENCES recordings(id),  -- one per recording
    engine       TEXT NOT NULL,                          -- e.g. 'whisperx' / 'null'
    model        TEXT,                                   -- e.g. 'large-v3'
    language     TEXT,                                   -- detected or forced
    json_path    TEXT,                                   -- full word-timestamped JSON
    text         TEXT,                                   -- plain text (for search)
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE segments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript_id     TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    idx               INTEGER NOT NULL,                  -- order within the transcript
    start_s           REAL NOT NULL,
    end_s             REAL NOT NULL,
    speaker_id        INTEGER,                           -- FK→speakers, set in M3
    diarization_label TEXT,                              -- raw 'SPEAKER_00', set in M3
    text              TEXT
);
CREATE INDEX idx_segments_transcript ON segments (transcript_id, start_s);
"""

# 004 — M2 speakers: cross-recording identities + their voiceprint embeddings
# (04 feature §4–5, 05 §4.5–4.6). `segments.speaker_id` / `diarization_label`
# (mig 003) and `devices.owner_speaker_id` (mig 001) are wired up here.
_MIGRATION_004 = """
CREATE TABLE speakers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name   TEXT,                                -- NULL until the user names it
    is_provisional INTEGER NOT NULL DEFAULT 1,          -- auto-created, unconfirmed
    needs_review   INTEGER NOT NULL DEFAULT 0,          -- uncertain match, flag for UI
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE voiceprints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    speaker_id          INTEGER NOT NULL REFERENCES speakers(id) ON DELETE CASCADE,
    embedding           BLOB NOT NULL,                  -- float32[dim], L2-normalized
    dim                 INTEGER NOT NULL,
    source_recording_id TEXT REFERENCES recordings(id),
    source_label        TEXT,                           -- diarization label it came from
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_voiceprints_speaker ON voiceprints (speaker_id);
"""

MIGRATIONS: Sequence[tuple[int, str]] = (
    (1, _MIGRATION_001),
    (2, _MIGRATION_002),
    (3, _MIGRATION_003),
    (4, _MIGRATION_004),
)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating parents) a SQLite connection in WAL mode with FKs on."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit; we manage txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Wait (don't immediately error) when another connection holds the write lock —
    # required for the multi-worker job runner's BEGIN IMMEDIATE claims (04 §7).
    conn.execute("PRAGMA busy_timeout=5000")
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
