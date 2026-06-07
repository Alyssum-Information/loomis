"""Explicit transaction helper for the autocommit connection.

``db.connect`` opens SQLite with ``isolation_level=None`` (autocommit), so any
multi-statement unit that must be atomic wraps itself in ``with transaction(conn):``
— commit on clean exit, rollback on any exception.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
