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
from .models import Device, JobType, Recording, RecordingStatus, TranscodePolicy
from .sqlite_tx import transaction
from .storage import Workspace, sha256_file, slugify

log = logging.getLogger("loomis.backup")


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
    )


def register_or_load_device(
    conn: sqlite3.Connection,
    volume: Path,
    settings: Settings,
    *,
    name: str | None = None,
    auto_delete: bool | None = None,
) -> Device:
    """Resolve the device for a volume, registering it on first sight (FR-1.2 … 1.6).

    Known ``device.json`` → ensure the DB row exists and return it. No file →
    generate an id, write ``device.json`` (best-effort; read-only volume is fine),
    and insert the DB row. The DB row is authoritative for backup policy.
    """
    path = device_file_path(volume)

    if path.exists():
        df = DeviceFile.load(path)
        existing = repository.find_device(conn, df.device_id)
        if existing is None:
            device = _device_from_file(df)
            repository.insert_device(conn, device)
        else:
            device = existing
        repository.touch_device(conn, device.id)
        return device

    # Unknown device → fresh registration.
    delete_policy = (
        auto_delete if auto_delete is not None else settings.backup.auto_delete_after_backup
    )
    df = DeviceFile(
        device_id=str(uuid4()),
        name=name or _default_device_name(volume),
        registered_at=_now_iso(),
        loomis_version=__version__,
        audio_globs=list(settings.backup.audio_globs),
        backup=DeviceBackup(auto_delete_after_backup=delete_policy),
        transcode=DeviceTranscode(policy=TranscodePolicy(settings.backup.transcode_policy)),
    )
    try:
        df.write(path)
    except OSError as exc:  # read-only / full volume → DB-only registration (FR-1.5)
        log.warning("could not write device.json to %s (%s); registering in DB only", path, exc)

    device = _device_from_file(df)
    repository.insert_device(conn, device)
    repository.touch_device(conn, device.id)
    return device


def _default_device_name(volume: Path) -> str:
    label = volume.name or str(volume).strip("\\/") or "Recorder"
    return f"Recorder ({label})"


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
    ws = Workspace(settings.core.resolved_data_dir)
    ws.ensure()
    globs = device.audio_globs or list(settings.backup.audio_globs)
    slug = slugify(device.name)
    report = BackupReport()

    for src in sorted(_iter_audio(volume, globs)):
        try:
            st = src.stat()
        except OSError:
            report.errors += 1
            continue

        # Cheap pre-check: identical path+size already imported → skip the hash.
        if repository.source_already_imported(conn, device.id, str(src), st.st_size):
            report.skipped += 1
            continue

        rec_id = uuid4().hex
        staged = ws.staging / f"{rec_id}{src.suffix}"

        # Step 3 — copy to staging; the original is never touched here.
        try:
            shutil.copy2(src, staged)
        except OSError:
            log.exception("copy failed: %s", src)
            staged.unlink(missing_ok=True)
            report.errors += 1
            continue

        # Step 4 — verify the copy against the source by SHA-256.
        try:
            source_hash = sha256_file(src)
            copy_hash = sha256_file(staged)
        except OSError:
            staged.unlink(missing_ok=True)
            report.errors += 1
            continue

        if source_hash != copy_hash:
            quarantined = ws.quarantine / staged.name
            os.replace(staged, quarantined)
            log.error("hash mismatch for %s; copy quarantined at %s", src, quarantined)
            report.quarantined += 1
            continue

        # Step 2 (authoritative) — content already in the ledger → drop the copy.
        if repository.recording_exists(conn, device.id, copy_hash):
            staged.unlink(missing_ok=True)
            report.duplicates += 1
            continue

        # Step 5 — commit: move into the library, then record the ledger row + job
        # atomically. recorded_at falls back to the source mtime (FR-2.8).
        recorded_at = datetime.fromtimestamp(st.st_mtime).astimezone()
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
            codec=(src.suffix.lstrip(".").lower() or None),
            recorded_at=recorded_at.isoformat(),
            status=RecordingStatus.IMPORTED,
        )
        try:
            with transaction(conn):
                repository.insert_recording(conn, rec)
                repository.enqueue_job(conn, JobType.STT, {"recording_id": rec_id})
        except Exception:
            # Don't leave an uncommitted library file orphaned.
            with suppress(OSError):
                lib_path.unlink()
            log.exception("commit failed for %s", src)
            report.errors += 1
            continue

        # Step 7 — optional source deletion, strictly after a verified, committed copy.
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
