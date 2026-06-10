"""Time-based triggers — the daemon's third leg beside the watcher and runner (04 §3.1).

Two schedules, both of which only *enqueue* durable jobs (the runner does the
work, so a missed tick or crash loses nothing):

- **Diary day-settled debounce** (feature 05 §3): a day's diary is aggregated
  once the day looks complete — every recording terminal and the newest import
  quiet for ``[summaries].diary_day_settle_minutes`` — instead of after every
  clip, so a day that fills up over hours costs one LLM pass, not one per clip.
  Late arrivals re-open the day: the next settled tick re-aggregates.
- **Cloud sync cron** (feature 06 §4): ``[cloud].schedule_cron`` enqueues a
  ``cloud_sync`` push when due (and cloud sync is enabled).

``tick`` is a pure function of the DB + clock so tests can drive it directly;
the daemon loops it on an interval.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from croniter import croniter

from .core import repository
from .core.config import Settings
from .core.models import JobType

if TYPE_CHECKING:
    from .core.events import EventBus

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 30.0  # how often the daemon evaluates the schedules


class Scheduler:
    def __init__(self, settings: Settings, bus: EventBus | None = None) -> None:
        self.settings = settings
        self.bus = bus
        self._next_sync: datetime | None = None  # computed lazily from the cron

    def tick(self, conn: sqlite3.Connection, *, now: datetime | None = None) -> int:
        """Evaluate both schedules once; returns how many jobs were enqueued."""
        now = now or datetime.now().astimezone()
        return self._tick_diaries(conn) + self._tick_cloud_sync(conn, now)

    def _tick_diaries(self, conn: sqlite3.Connection) -> int:
        settle = self.settings.summaries.diary_day_settle_minutes
        enqueued = 0
        for date in repository.due_diary_dates(conn, settle_minutes=settle):
            payload: dict[str, object] = {"date": date}
            if repository.has_pending_job(conn, JobType.DIARY_AGGREGATE, payload):
                continue
            repository.enqueue_job(conn, JobType.DIARY_AGGREGATE, payload)
            enqueued += 1
            log.info("day %s settled; diary aggregation enqueued", date)
        return enqueued

    def _tick_cloud_sync(self, conn: sqlite3.Connection, now: datetime) -> int:
        cloud = self.settings.cloud
        if not cloud.enabled or not cloud.schedule_cron or not cloud.remotes:
            return 0
        if self._next_sync is None:
            # First tick (or restart): schedule from now — no catch-up runs for
            # downtime; rclone copy is incremental, the next run covers it.
            self._next_sync = croniter(cloud.schedule_cron, now).get_next(datetime)
            return 0
        if now < self._next_sync:
            return 0
        self._next_sync = croniter(cloud.schedule_cron, now).get_next(datetime)
        if repository.has_pending_job(conn, JobType.CLOUD_SYNC, {}):
            return 0  # previous scheduled push still queued/running
        repository.enqueue_job(conn, JobType.CLOUD_SYNC, {})
        log.info("scheduled cloud sync enqueued (cron %r)", cloud.schedule_cron)
        return 1
