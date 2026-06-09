"""The in-process background daemon (04 §3).

Runs the durable job runner and the removable-device watcher as background threads
inside the API process, so a single process is the only SQLite writer and the
WebSocket can stream live progress. Started/stopped by the FastAPI lifespan
(``app.py``) when ``[api].run_daemon`` is set; the standalone ``loomis worker`` /
``loomis backup`` CLIs remain available for headless use.

Each thread owns its own SQLite connection (SQLite connections are not shareable
across threads); WAL mode lets the watcher import while the runner processes and
request handlers read.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from . import backup, db
from .config import Settings
from .events import EventBus
from .jobs import JobRunner
from .watcher import DeviceWatcher

log = logging.getLogger(__name__)

_JOIN_TIMEOUT = 10.0


class Daemon:
    """Owns the background worker threads and their lifecycle."""

    def __init__(self, settings: Settings, bus: EventBus) -> None:
        self.settings = settings
        self.bus = bus
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._runner = JobRunner(settings, bus=bus)

    @property
    def _db_path(self) -> Path:
        return self.settings.core.resolved_data_dir / "loomis.db"

    def start(self) -> None:
        """Spawn the job-runner and device-watcher threads (idempotent)."""
        if self._threads:
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(
                target=self._runner.serve, args=(self._stop,), name="daemon-runner", daemon=True
            ),
            threading.Thread(target=self._watch_loop, name="daemon-watcher", daemon=True),
        ]
        for t in self._threads:
            t.start()
        log.info("daemon started (runner + watcher)")

    def stop(self) -> None:
        """Signal threads to stop and wait for them to drain."""
        self._stop.set()
        for t in self._threads:
            t.join(timeout=_JOIN_TIMEOUT)
        self._threads = []
        log.info("daemon stopped")

    def _watch_loop(self) -> None:
        conn = db.connect(self._db_path)  # this thread's own connection
        try:
            watcher = DeviceWatcher(self.settings.backup.poll_interval_s)
            watcher.watch(lambda vol: self._on_connect(conn, vol), stop=self._stop)
        finally:
            conn.close()

    def _on_connect(self, conn: sqlite3.Connection, volume: Path) -> None:
        """Import a connected recorder **only if it is registered** (FR-1.9).

        Unregistered volumes just raise a prompt over the bus — nothing is written
        to them and no row is created. One bad volume (e.g. a malformed device.json)
        must not kill the watcher thread, so failures are logged and swallowed.
        """
        try:
            device = backup.resolve_device(conn, volume)
            if device is None or not device.registered:
                # Opt-in: prompt the user; never auto-register or import (FR-1.9).
                self.bus.publish(
                    "device.connected",
                    {
                        "device_id": device.id if device else None,
                        "volume": str(volume),
                        "registered": False,
                    },
                )
                return
            report = backup.run_backup(conn, device, volume, self.settings)
        except Exception:
            log.exception("daemon import failed for %s; skipped", volume)
            return
        self.bus.publish(
            "device.connected",
            {"device_id": device.id, "volume": str(volume), "registered": True},
        )
        for rec_id in report.imported_ids:
            self.bus.publish("recording.added", {"recording_id": rec_id, "device_id": device.id})
        log.info("daemon imported %d new recording(s) from %s", report.imported, volume)
