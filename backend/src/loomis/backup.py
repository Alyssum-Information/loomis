"""Backup & ingest — the data-integrity safety spine (FR-2.1 … FR-2.8).

Per source file, the strict order is: copy → **SHA-256 verify** → dedupe →
commit to the library + ledger → (optional) delete source. A source file is
removed only after a verified, committed library copy exists; a hash mismatch
quarantines the copy and never touches the source
([04 §8](../../docs/04-system-architecture.md#8-data-integrity-the-safety-spine),
[features/01](../../docs/features/01-device-registration-and-backup.md)).
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from . import __version__, repository
from .config import Settings
from .devicefile import DeviceBackup, DeviceFile, DeviceTranscode, device_file_path
from .models import Device, JobType, Quarantine, Recording, RecordingStatus, TranscodePolicy
from .sqlite_tx import transaction
from .storage import Workspace, sha256_file, slugify

log = logging.getLogger(__name__)


@dataclass(slots=True)
class BackupReport:
    """Tally of one backup pass (one device, one connect)."""

    imported: int = 0
    skipped: int = 0  # cheap path+size pre-check hit
    duplicates: int = 0  # same content already in the ledger
    quarantined: int = 0  # copy failed SHA-256 verification
    deleted: int = 0  # source removed after a verified backup
    errors: int = 0
    imported_ids: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _device_from_file(df: DeviceFile) -> Device:
    return Device(
        id=df.device_id,
        name=df.name,
        audio_globs=df.audio_globs,
        auto_delete=df.backup.auto_delete_after_backup,
        transcode_policy=df.transcode.policy,
        transcode_opts={
            "codec": df.transcode.codec,
            "bitrate": df.transcode.bitrate,
            "application": df.transcode.application,
        },
        min_free_bytes=df.backup.min_free_bytes_guard,
    )


def _first_step(policy: TranscodePolicy) -> JobType:
    """Pipeline entry point for a new recording: transcode first unless we keep the original."""
    return JobType.STT if policy == TranscodePolicy.KEEP_ORIGINAL else JobType.TRANSCODE


def register_or_load_device(
    conn: sqlite3.Connection,
    volume: Path,
    settings: Settings,
    *,
    name: str | None = None,
    auto_delete: bool | None = None,
) -> Device:
    """Resolve the device for a volume, registering it on first sight (FR-1.2 … 1.6).

    Known ``device.json`` → ensure the DB row exists and return it. No file → fall
    back to the volume's identity so an unwritable (read-only/full) recorder still
    resolves to one stable row across reconnects (FR-1.5); otherwise generate an
    id, write ``device.json`` (best-effort), and insert the row. The DB row is
    authoritative for backup policy.
    """
    path = device_file_path(volume)
    if path.exists():
        df = DeviceFile.load(path)
        device = repository.find_device(conn, df.device_id) or _register(
            conn, _device_from_file(df)
        )
        repository.touch_device(conn, device.id)
        return device

    serial = _volume_identity(volume)
    existing = repository.find_device_by_serial(conn, serial)
    if existing is not None:
        repository.touch_device(conn, existing.id)
        return existing

    delete_policy = (
        auto_delete if auto_delete is not None else settings.backup.auto_delete_after_backup
    )
    df = DeviceFile(
        device_id=str(uuid4()),
        name=name or _default_device_name(serial),
        registered_at=_now_iso(),
        loomis_version=__version__,
        audio_globs=list(settings.backup.audio_globs),
        backup=DeviceBackup(auto_delete_after_backup=delete_policy),
        transcode=DeviceTranscode(policy=settings.backup.transcode_policy),
    )
    try:
        df.write(path)
    except OSError as exc:  # read-only / full volume → DB-only registration (FR-1.5)
        log.warning("could not write device.json to %s (%s); registering in DB only", path, exc)

    device = _device_from_file(df)
    device.volume_serial = serial  # identity fallback when device.json is unavailable
    return _register(conn, device)


def _register(conn: sqlite3.Connection, device: Device) -> Device:
    repository.insert_device(conn, device)
    repository.touch_device(conn, device.id)
    return device


def _volume_identity(volume: Path) -> str:
    """Stable-enough key for a volume lacking ``device.json``.

    psutil exposes no portable hardware serial, so the volume label / mountpoint
    stands in: enough to avoid duplicate registrations on reconnect (FR-1.5).
    """
    return volume.name or str(volume).strip("\\/") or "recorder"


def _default_device_name(serial: str) -> str:
    return f"Recorder ({serial})"


def _iter_audio(volume: Path, globs: list[str]) -> Iterator[Path]:
    """Yield distinct audio files under ``volume`` matching any glob, skipping ``.loomis``."""
    seen: set[Path] = set()
    for pattern in globs:
        for path in volume.glob(pattern):
            if path.is_file() and ".loomis" not in path.parts and path not in seen:
                seen.add(path)
                yield path


def run_backup(
    conn: sqlite3.Connection,
    device: Device,
    volume: Path,
    settings: Settings,
) -> BackupReport:
    """Import new audio from ``volume`` for ``device`` under the safety spine."""
    ws = Workspace(settings.core.resolved_data_dir, settings.backup.staging_dir)
    ws.ensure()
    orphans = ws.clear_staging()  # discard debris from any crashed prior run (Feature 01 §6)
    if orphans:
        log.info("cleared %d orphaned staging file(s)", orphans)
    globs = device.audio_globs or list(settings.backup.audio_globs)
    slug = slugify(device.name)
    report = BackupReport()

    for src in sorted(_iter_audio(volume, globs)):
        try:
            st = src.stat()
        except OSError:
            report.errors += 1
            continue

        # Capture timestamp falls back to the source mtime (FR-2.8); also part of the
        # pre-check key below.
        recorded_at = datetime.fromtimestamp(st.st_mtime).astimezone()
        recorded_at_iso = recorded_at.isoformat()

        # Dedupe, cheap pre-check (FR-2.2): identical path+size+mtime already imported →
        # skip before paying for a copy + hash.
        if repository.source_already_imported(
            conn, device.id, str(src), st.st_size, recorded_at_iso
        ):
            report.skipped += 1
            continue

        # Free-space guard: never start a copy that would leave the disk below the
        # device's threshold (device.json ``min_free_bytes_guard``). Source kept.
        if device.min_free_bytes:
            free = shutil.disk_usage(ws.data_dir).free
            if free - st.st_size < device.min_free_bytes:
                log.error(
                    "low disk space; skipping %s (free=%d, need %d after copy)",
                    src,
                    free,
                    device.min_free_bytes,
                )
                report.errors += 1
                continue

        rec_id = uuid4().hex
        staged = ws.staging / f"{rec_id}{src.suffix}"

        # Copy to staging (FR-2.3); the original is never touched here.
        try:
            shutil.copy2(src, staged)
        except OSError:
            log.exception("copy failed: %s", src)
            staged.unlink(missing_ok=True)
            report.errors += 1
            continue

        # Verify the copy against the source by SHA-256 (FR-2.4) — the integrity gate.
        try:
            source_hash = sha256_file(src)
            copy_hash = sha256_file(staged)
        except OSError:
            staged.unlink(missing_ok=True)
            report.errors += 1
            continue

        if source_hash != copy_hash:  # corrupt copy → quarantine, never delete source (FR-2.7)
            parked = ws.quarantine / staged.name
            os.replace(staged, parked)
            repository.insert_quarantine(
                conn,
                Quarantine(
                    id=rec_id,
                    device_id=device.id,
                    source_path=str(src),
                    quarantine_path=str(parked),
                    reason="hash_mismatch",
                    size_bytes=st.st_size,
                ),
            )
            log.error("hash mismatch for %s; copy quarantined at %s", src, parked)
            report.quarantined += 1
            continue

        # Dedupe, authoritative (FR-2.2): these exact bytes already in the ledger → drop the copy.
        if repository.recording_exists(conn, device.id, copy_hash):
            staged.unlink(missing_ok=True)
            report.duplicates += 1
            continue

        # Commit (FR-2.6): move into the library, then write the ledger row + pipeline
        # job atomically.
        lib_path = ws.library_path(slug, recorded_at, rec_id, src.suffix)
        lib_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, lib_path)  # atomic within the data_dir filesystem

        rec = Recording(
            id=rec_id,
            device_id=device.id,
            source_path=str(src),
            library_path=str(lib_path),
            sha256=copy_hash,
            size_bytes=st.st_size,
            codec=None,  # actual codec is probed during transcode/STT (M2); container ≠ codec
            recorded_at=recorded_at_iso,
            status=RecordingStatus.IMPORTED,
        )
        # First pipeline step follows the device policy: transcode unless keeping the
        # original (matches import → transcode? → stt). The worker arrives in M2.
        first_step = _first_step(device.transcode_policy)
        try:
            with transaction(conn):
                repository.insert_recording(conn, rec)
                repository.enqueue_job(conn, first_step, {"recording_id": rec_id})
        except Exception:
            # Don't leave an uncommitted library file orphaned.
            with suppress(OSError):
                lib_path.unlink()
            log.exception("commit failed for %s", src)
            report.errors += 1
            continue

        # Optional source deletion (FR-2.5), strictly after a verified, committed copy.
        if device.auto_delete:
            try:
                src.unlink()
                repository.mark_source_deleted(conn, rec_id)
                report.deleted += 1
            except OSError:
                log.warning("auto-delete failed for %s; source kept", src)

        report.imported += 1
        report.imported_ids.append(rec_id)

    return report
