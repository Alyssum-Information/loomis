"""Command-line entry point: ``loomis <command>``.

Stdlib argparse keeps the base dependency-free. The default (no subcommand) and
``up`` launch the one-click backend+frontend dev stack (see ``launcher.py``);
``serve`` runs only the API; ``check`` reports prerequisites; ``backup`` imports
audio from a recorder under the safety spine (M1).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import suppress
from pathlib import Path

from . import __version__
from .config import Settings, get_settings


def _up(args: argparse.Namespace) -> int:
    from . import launcher

    return launcher.up(prod=args.prod, open_browser=args.browser)


def _check(_: argparse.Namespace) -> int:
    from . import launcher

    return 0 if launcher.run_prerequisite_check(need_frontend=True) else 1


def _open_db(settings: Settings) -> sqlite3.Connection:
    """Open the library DB and bring the schema up to date."""
    from . import db

    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(data_dir / "loomis.db")
    db.apply_migrations(conn)
    return conn


def _backup_one(
    conn: sqlite3.Connection,
    settings: Settings,
    volume: Path,
    *,
    name: str | None,
    auto_delete: bool | None,
) -> None:
    import logging

    from . import backup

    if not volume.exists():
        print(f"volume not found: {volume}")
        return
    # One bad device (e.g. a malformed device.json) must not abort the whole run —
    # critical in --watch mode. Log and skip; never overwrite the user's file.
    try:
        device = backup.register_or_load_device(
            conn, volume, settings, name=name, auto_delete=auto_delete
        )
        report = backup.run_backup(conn, device, volume, settings)
    except Exception:
        logging.getLogger(__name__).exception("backup failed for %s", volume)
        print(f"  ! backup failed for {volume}; skipped - see the log above.")
        return
    print(
        f"[{device.name}] imported={report.imported} skipped={report.skipped} "
        f"duplicates={report.duplicates} quarantined={report.quarantined} "
        f"deleted={report.deleted} errors={report.errors}"
    )
    if report.quarantined or report.errors:
        print("  ! some files were quarantined or failed - see the log above for details.")


def _backup(args: argparse.Namespace) -> int:
    from .logging_setup import configure_logging
    from .watcher import DeviceWatcher

    settings = get_settings()
    configure_logging(settings.core.log_level)
    auto_delete: bool | None = True if args.auto_delete else None
    conn = _open_db(settings)
    try:
        if args.watch:
            print("Watching for removable volumes — Ctrl-C to stop.")
            watcher = DeviceWatcher(settings.backup.poll_interval_s)
            try:
                watcher.watch(
                    lambda vol: _backup_one(
                        conn, settings, vol, name=args.name, auto_delete=auto_delete
                    )
                )
            except KeyboardInterrupt:
                print("\nStopped.")
            return 0

        if args.volume is None:
            print("specify a VOLUME path or use --watch")
            return 2
        _backup_one(conn, settings, Path(args.volume), name=args.name, auto_delete=auto_delete)
        return 0
    finally:
        conn.close()


def _worker(args: argparse.Namespace) -> int:
    import threading

    from .jobs import JobRunner
    from .logging_setup import configure_logging
    from .pipeline import HANDLERS

    settings = get_settings()
    configure_logging(settings.core.log_level)

    handlers = HANDLERS
    if args.types:
        from .models import JobType

        wanted = {JobType(t.strip()) for t in args.types.split(",") if t.strip()}
        handlers = {k: v for k, v in HANDLERS.items() if k in wanted}

    runner = JobRunner(settings, handlers)
    conn = _open_db(settings)
    try:
        if args.once:
            n = runner.drain(conn)
            print(f"processed {n} job(s)")
            return 0
    finally:
        conn.close()

    # Long-running mode: a bounded worker pool until Ctrl-C.
    print("Job runner started - Ctrl-C to stop.")
    stop = threading.Event()
    pool = threading.Thread(target=runner.serve, args=(stop,), name="job-runner")
    pool.start()
    try:
        while pool.is_alive():
            pool.join(0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
        stop.set()
        pool.join()
    return 0


def _serve(_: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    # import string so uvicorn can manage the app lifecycle / reload
    uvicorn.run(
        "loomis.app:create_app",
        factory=True,
        host=settings.api.host,
        port=settings.api.port,
    )
    return 0


def _version(_: argparse.Namespace) -> int:
    print(f"loomis {__version__}")
    return 0


def _add_up_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prod",
        action="store_true",
        help="build the SPA and serve it from the backend (no Vite dev server)",
    )
    parser.add_argument(
        "--no-browser",
        dest="browser",
        action="store_false",
        help="do not open a browser window on startup",
    )
    parser.set_defaults(func=_up, prod=False, browser=True)


def main(argv: list[str] | None = None) -> int:
    # Never let a non-ASCII path or message hard-crash on a legacy console codepage
    # (e.g. Windows cp950); degrade unencodable chars instead of raising.
    with suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(prog="loomis", description="Loomis backend CLI")
    # No subcommand → `up`, the one-click dev launcher.
    _add_up_flags(parser)
    sub = parser.add_subparsers(dest="command")

    p_up = sub.add_parser("up", help="launch backend + frontend (one-click dev)")
    _add_up_flags(p_up)

    p_check = sub.add_parser("check", help="report prerequisite tool status")
    p_check.set_defaults(func=_check)

    p_backup = sub.add_parser("backup", help="import audio from a recorder volume")
    p_backup.add_argument("volume", nargs="?", help="mounted recorder volume (e.g. E:\\)")
    p_backup.add_argument(
        "--watch", action="store_true", help="poll for volumes and import on connect"
    )
    p_backup.add_argument("--name", help="device name to use on first registration")
    p_backup.add_argument(
        "--auto-delete",
        action="store_true",
        help="delete each source file after its backup is verified (FR-2.5)",
    )
    p_backup.set_defaults(func=_backup)

    p_worker = sub.add_parser(
        "worker", help="run the pipeline job runner (transcode, stt, diarize, speaker_id)"
    )
    p_worker.add_argument(
        "--once", action="store_true", help="drain the queue once and exit (no polling loop)"
    )
    p_worker.add_argument("--types", help="comma-separated job types to handle (default: all)")
    p_worker.set_defaults(func=_worker)

    p_serve = sub.add_parser("serve", help="run only the FastAPI API")
    p_serve.set_defaults(func=_serve)

    p_version = sub.add_parser("version", help="print version")
    p_version.set_defaults(func=_version)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
