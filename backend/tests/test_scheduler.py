"""Scheduler (04 §3.1): diary day-settled debounce + cloud sync cron."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from loomis.core import db, repository
from loomis.core.config import (
    BackupSettings,
    CloudRemote,
    CloudSettings,
    CoreSettings,
    Settings,
    SummariesSettings,
)
from loomis.core.models import (
    Device,
    DiaryEntry,
    JobType,
    Recording,
    RecordingKind,
    RecordingStatus,
    TranscodePolicy,
)
from loomis.scheduler import Scheduler


def _settings(tmp_path: Path, *, settle_minutes: int = 0, cron: str = "") -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        backup=BackupSettings(
            folder_settle_seconds=0.0, transcode_policy=TranscodePolicy.KEEP_ORIGINAL
        ),
        summaries=SummariesSettings(diary_day_settle_minutes=settle_minutes),
        cloud=CloudSettings(
            enabled=bool(cron),
            schedule_cron=cron,
            remotes=[CloudRemote(name="onedrive")] if cron else [],
        ),
    )


def _conn(settings: Settings) -> sqlite3.Connection:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    c = db.connect(data_dir / "loomis.db")
    db.apply_migrations(c)
    return c


def _seed_recording(
    conn: sqlite3.Connection,
    rec_id: str,
    *,
    status: RecordingStatus = RecordingStatus.DONE,
    kind: RecordingKind | None = RecordingKind.DIARY,
) -> None:
    if repository.find_device(conn, "dev-1") is None:
        repository.insert_device(conn, Device(id="dev-1", name="Recorder"))
    repository.insert_recording(
        conn,
        Recording(
            id=rec_id,
            device_id="dev-1",
            source_path=f"{rec_id}.wav",
            library_path=f"{rec_id}.wav",
            sha256=f"h-{rec_id}",
            size_bytes=1,
            recorded_at="2026-06-09T10:00:00+08:00",
            status=status,
        ),
    )
    if kind is not None:
        repository.set_recording_kind(conn, rec_id, kind)


def _pending_jobs(conn: sqlite3.Connection, job_type: JobType) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE type = ? AND status IN ('queued', 'running')",
        (job_type.value,),
    ).fetchone()
    return int(row["n"])


# --- diary day-settled debounce (feature 05 §3) ---


def test_settled_day_enqueues_diary_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1")
    scheduler = Scheduler(settings)

    assert scheduler.tick(conn) == 1
    assert _pending_jobs(conn, JobType.DIARY_AGGREGATE) == 1

    # The job is still pending → the next tick must not duplicate it.
    assert scheduler.tick(conn) == 0
    assert _pending_jobs(conn, JobType.DIARY_AGGREGATE) == 1


def test_fresh_diary_is_not_reaggregated(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1")
    # Diary already written after the last import → nothing to do.
    repository.replace_diary_entry(
        conn, DiaryEntry(id="d-1", date="2026-06-09", title="Day"), ["rec-1"]
    )
    assert Scheduler(settings).tick(conn) == 0


def test_late_arrival_reopens_the_day(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1")
    repository.replace_diary_entry(
        conn, DiaryEntry(id="d-1", date="2026-06-09", title="Day"), ["rec-1"]
    )
    # A clip that arrived after the last aggregation makes the entry stale.
    conn.execute("UPDATE diary_entries SET updated_at = datetime('now', '-1 hour')")
    assert Scheduler(settings).tick(conn) == 1


def test_busy_day_is_not_settled(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1")
    _seed_recording(conn, "rec-2", status=RecordingStatus.PROCESSING)
    assert Scheduler(settings).tick(conn) == 0  # a clip is still in the pipeline


def test_settle_window_defers_aggregation(tmp_path: Path) -> None:
    settings = _settings(tmp_path, settle_minutes=30)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1")  # imported_at = now → inside the quiet window
    assert Scheduler(settings).tick(conn) == 0

    conn.execute("UPDATE recordings SET imported_at = datetime('now', '-31 minutes')")
    assert Scheduler(settings).tick(conn) == 1


def test_unclassified_recordings_are_ignored(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_recording(conn, "rec-1", kind=None)  # failed before classify
    assert Scheduler(settings).tick(conn) == 0


# --- cloud sync cron (feature 06 §4) ---


def test_cron_enqueues_cloud_sync_when_due(tmp_path: Path) -> None:
    settings = _settings(tmp_path, cron="*/5 * * * *")
    conn = _conn(settings)
    scheduler = Scheduler(settings)
    t0 = datetime(2026, 6, 10, 12, 0, 30).astimezone()

    # First tick only primes the schedule (no catch-up runs).
    assert scheduler.tick(conn, now=t0) == 0
    assert _pending_jobs(conn, JobType.CLOUD_SYNC) == 0

    # Past the next cron point → one push enqueued.
    assert scheduler.tick(conn, now=t0 + timedelta(minutes=6)) == 1
    assert _pending_jobs(conn, JobType.CLOUD_SYNC) == 1

    # Still queued at the following cron point → no duplicate.
    assert scheduler.tick(conn, now=t0 + timedelta(minutes=12)) == 0
    assert _pending_jobs(conn, JobType.CLOUD_SYNC) == 1


def test_cron_idle_without_schedule_or_when_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path)  # cloud disabled, no cron
    conn = _conn(settings)
    assert Scheduler(settings).tick(conn) == 0
    assert _pending_jobs(conn, JobType.CLOUD_SYNC) == 0
