"""The durable job runner — the worker side of the SQLite job queue (04 §7).

Workers atomically claim a job, run its handler, and mark it done or failed
(retry, or park after ``[jobs].max_attempts``). A crashed worker's ``running``
job is reclaimed once its lease expires. ``drain`` runs the queue to empty on one
connection (CLI ``--once`` / tests); ``serve`` runs a bounded pool until stopped.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

from . import db, repository
from .config import Settings
from .models import JobStatus, JobType, RecordingStatus
from .pipeline import HANDLERS, Handler, JobContext

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, settings: Settings, handlers: dict[JobType, Handler] | None = None) -> None:
        self.settings = settings
        self.handlers: dict[JobType, Handler] = handlers if handlers is not None else HANDLERS
        self._types = tuple(self.handlers)

    def _execute_one(self, conn: sqlite3.Connection, worker_id: str) -> bool:
        """Claim and run a single job. Returns False when the queue has no runnable job."""
        job = repository.claim_job(
            conn,
            worker_id,
            lease_seconds=self.settings.jobs.lease_seconds,
            types=self._types,
        )
        if job is None or job.id is None:
            return job is not None
        job_id = job.id
        handler: Handler | None = self.handlers.get(job.type)
        if handler is None:  # defensive: claim filters by type, so this shouldn't happen
            repository.fail_job(conn, job_id, f"no handler for {job.type}", max_attempts=1)
            return True
        try:
            handler(JobContext(conn, self.settings), job)
            repository.complete_job(conn, job_id)
            log.info("job %s (%s) done", job_id, job.type)
        except Exception as exc:  # noqa: BLE001 (a handler failure must not kill the worker)
            log.exception("job %s (%s) failed", job_id, job.type)
            status = repository.fail_job(
                conn, job_id, repr(exc), max_attempts=self.settings.jobs.max_attempts
            )
            # Dead-lettered: surface it on the recording so it isn't stuck "processing".
            if status == JobStatus.PARKED:
                rec_id = job.payload.get("recording_id")
                if isinstance(rec_id, str):
                    repository.set_recording_status(conn, rec_id, RecordingStatus.FAILED)
        return True

    def drain(self, conn: sqlite3.Connection) -> int:
        """Process jobs until none remain runnable; returns the number executed."""
        worker_id = f"drain-{uuid4().hex[:8]}"
        processed = 0
        while self._execute_one(conn, worker_id):
            processed += 1
        return processed

    def serve(self, stop: threading.Event) -> None:
        """Run ``[jobs].concurrency`` worker threads until ``stop`` is set."""
        db_path = self.settings.core.resolved_data_dir / "loomis.db"
        workers = max(1, self.settings.jobs.concurrency)
        threads = [
            threading.Thread(
                target=self._worker_loop, args=(stop, db_path, f"worker-{i}"), name=f"job-{i}"
            )
            for i in range(workers)
        ]
        for t in threads:
            t.start()
        log.info("job runner up: %d worker(s)", workers)
        for t in threads:
            t.join()

    def _worker_loop(self, stop: threading.Event, db_path: Path, worker_id: str) -> None:
        conn = db.connect(db_path)  # one connection per worker (sqlite is not thread-safe)
        try:
            while not stop.is_set():
                if not self._execute_one(conn, worker_id):
                    stop.wait(self.settings.jobs.poll_interval_s)
        finally:
            conn.close()
