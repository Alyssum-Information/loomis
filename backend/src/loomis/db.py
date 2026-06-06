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
# The real data model (recordings, devices, jobs, …) arrives with M1.
MIGRATIONS: Sequence[tuple[int, str]] = ()


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


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply any pending migrations in a single transaction each. Returns final version."""
    version = _current_version(conn)
    for target, sql in MIGRATIONS:
        if target <= version:
            continue
        conn.execute("BEGIN")
        try:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (target,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        version = target
    return version
