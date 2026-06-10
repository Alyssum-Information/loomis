"""The cloud_sync job: push configured scopes to each rclone remote (FR-8.1–8.4).

Runs as a durable job (enqueued by ``POST /cloud/sync`` or the scheduler), so it
retries like any pipeline step and its outcome is queryable twice over: the job
row and a per-remote ``cloud_sync_log`` row (05 §4.14).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from ..core import repository
from ..core.config import CloudRemote, Settings
from ..core.errors import PermanentJobError
from ..core.models import Job
from .rclone import Rclone

if TYPE_CHECKING:
    from ..pipeline.steps import JobContext

log = logging.getLogger(__name__)

# What each scope pushes, relative to data_dir. ``db`` is special-cased: the live
# SQLite file can't be copied safely under WAL, so a consistent snapshot is taken
# first (see _db_snapshot).
_SCOPE_DIRS: dict[str, list[str]] = {
    "audio": ["library"],
    "markdown": ["diary", "meetings"],
}


def _db_snapshot(conn: sqlite3.Connection, data_dir: Path) -> Path:
    """A consistent copy of the DB for upload (FR-9.4).

    ``VACUUM INTO`` writes a compact, transaction-consistent snapshot even while
    WAL writers are active — copying ``loomis.db`` directly would race them.
    """
    out = data_dir / "cache" / "db-backup" / "loomis.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)  # VACUUM INTO refuses to overwrite
    conn.execute("VACUUM INTO ?", (str(out),))
    return out


def sync_remote(
    conn: sqlite3.Connection,
    settings: Settings,
    remote: CloudRemote,
    *,
    rclone: Rclone | None = None,
) -> None:
    """Push one remote's scopes; records a ``cloud_sync_log`` row either way.

    Raises on failure so the surrounding job retries; partial progress is safe
    (rclone copy is incremental and never deletes).
    """
    rclone = rclone or Rclone(settings.cloud.rclone_path)
    data_dir = settings.core.resolved_data_dir
    log_id = repository.start_cloud_sync(conn, remote.name, list(remote.scope))
    stats: dict[str, object] = {}
    try:
        for scope in remote.scope:
            if scope == "db":
                snapshot = _db_snapshot(conn, data_dir)
                stats["db"] = rclone.copy(snapshot, f"{remote.name}:{remote.dest}/db")
                continue
            for sub in _SCOPE_DIRS[scope]:
                src = data_dir / sub
                if not src.is_dir():
                    continue  # nothing produced yet for this scope
                stats[sub] = rclone.copy(src, f"{remote.name}:{remote.dest}/{sub}")
    except Exception as exc:
        repository.finish_cloud_sync(conn, log_id, "error", {**stats, "error": str(exc)[:500]})
        raise
    repository.finish_cloud_sync(conn, log_id, "ok", stats)
    log.info("cloud sync ok: remote=%s scope=%s", remote.name, ",".join(remote.scope))


def handle_cloud_sync(ctx: JobContext, job: Job) -> None:
    """Job handler: push every configured remote, or just ``payload.remote`` (FR-8.3)."""
    cloud = ctx.settings.cloud
    if not cloud.enabled:
        # Config changed between enqueue and execution; never sync while disabled (NFR-1).
        raise PermanentJobError("cloud sync is disabled ([cloud].enabled = false)")
    wanted = job.payload.get("remote")
    remotes = [r for r in cloud.remotes if wanted in (None, r.name)]
    if not remotes:
        raise PermanentJobError(f"no matching cloud remote configured: {wanted!r}")
    for remote in remotes:
        if ctx.bus is not None:
            # The UI's egress indicator: data is about to leave the machine (FR-7.8).
            ctx.bus.publish("egress.started", {"kind": "cloud_sync", "detail": remote.name})
        sync_remote(ctx.conn, ctx.settings, remote)
        if ctx.bus is not None:
            ctx.bus.publish("cloud.synced", {"remote": remote.name})
