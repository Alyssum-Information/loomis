"""Durable job queue: atomic claim, retry/park, and crash-reclaim (04 §7)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loomis.core import db, repository
from loomis.core.models import JobType


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "loomis.db")
    db.apply_migrations(c)
    return c


def _enqueue(conn: sqlite3.Connection) -> int:
    return repository.enqueue_job(conn, JobType.STT, {"recording_id": "r1"})


def test_claim_marks_running_and_blocks_second_claim(conn: sqlite3.Connection) -> None:
    jid = _enqueue(conn)
    job = repository.claim_job(conn, "w1", lease_seconds=600, types=(JobType.STT,))
    assert job is not None
    assert job.id == jid
    assert job.attempts == 1
    # Nothing else runnable → a second claim returns None.
    assert repository.claim_job(conn, "w2", lease_seconds=600) is None


def test_complete_marks_done(conn: sqlite3.Connection) -> None:
    jid = _enqueue(conn)
    repository.claim_job(conn, "w1", lease_seconds=600)
    repository.complete_job(conn, jid)
    assert (
        conn.execute("SELECT status FROM jobs WHERE id = ?", (jid,)).fetchone()["status"] == "done"
    )


def test_fail_retries_then_parks(conn: sqlite3.Connection) -> None:
    jid = _enqueue(conn)
    # attempt 1 → still under max → requeued
    repository.claim_job(conn, "w1", lease_seconds=600)
    repository.fail_job(conn, jid, "boom", max_attempts=2)
    assert (
        conn.execute("SELECT status FROM jobs WHERE id = ?", (jid,)).fetchone()["status"]
        == "queued"
    )
    # attempt 2 → reaches max → parked (dead-letter)
    repository.claim_job(conn, "w1", lease_seconds=600)
    repository.fail_job(conn, jid, "boom", max_attempts=2)
    row = conn.execute("SELECT status, last_error FROM jobs WHERE id = ?", (jid,)).fetchone()
    assert row["status"] == "parked"
    assert row["last_error"] == "boom"


def test_stale_running_job_is_reclaimed(conn: sqlite3.Connection) -> None:
    jid = _enqueue(conn)
    conn.execute(
        "UPDATE jobs SET status='running', worker_id='dead', "
        "updated_at=datetime('now','-1 hour') WHERE id = ?",
        (jid,),
    )
    job = repository.claim_job(conn, "w2", lease_seconds=600)  # 1h idle > 600s lease
    assert job is not None
    assert job.id == jid


def test_fresh_running_job_is_not_reclaimed(conn: sqlite3.Connection) -> None:
    jid = _enqueue(conn)
    conn.execute(
        "UPDATE jobs SET status='running', updated_at=datetime('now') WHERE id = ?", (jid,)
    )
    assert repository.claim_job(conn, "w2", lease_seconds=600) is None


def test_type_filter_skips_other_types(conn: sqlite3.Connection) -> None:
    repository.enqueue_job(conn, JobType.TRANSCODE, {"recording_id": "r1"})
    # A worker that only handles STT must not grab a transcode job.
    assert repository.claim_job(conn, "w1", lease_seconds=600, types=(JobType.STT,)) is None
