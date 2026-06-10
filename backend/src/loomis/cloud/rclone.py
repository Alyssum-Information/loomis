"""Thin wrapper around the rclone binary (ADR-0004).

Remotes are configured with rclone's own tooling (``rclone config``); Loomis
only references them by name. Credentials therefore live in rclone's config —
never in Loomis settings, the DB, or logs (NFR-9).

Only ``rclone copy`` is ever issued: copy adds/updates files on the remote and
**never deletes** on either side — the mechanical guarantee behind the
push-only promise (FR-8.4). ``rclone sync`` (which mirrors deletions) is
deliberately not exposed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..core.errors import PermanentJobError


class RcloneError(RuntimeError):
    """rclone exited non-zero; the message carries its stderr tail."""


class Rclone:
    def __init__(self, rclone_path: str = "rclone") -> None:
        self._path = rclone_path

    def available(self) -> bool:
        return shutil.which(self._path) is not None

    def copy_args(self, src: Path, dest: str) -> list[str]:
        """The exact argv for one push — separated out so tests can pin it down."""
        return [
            self._path,
            "copy",  # never "sync": copy cannot delete anything (FR-8.4)
            str(src),
            dest,
            "--stats-one-line",
            "--stats-log-level",
            "NOTICE",
        ]

    def copy(self, src: Path, dest: str) -> str:
        """Push ``src`` (file or directory) to ``dest`` (``remote:path``).

        Returns rclone's stats line for the sync log. Raises
        :class:`PermanentJobError` when the binary is missing (retrying won't
        help) and :class:`RcloneError` on a failed transfer (retryable).
        """
        if not self.available():
            raise PermanentJobError(
                f"rclone not found on PATH ({self._path}) — install it and run `rclone config`"
            )
        result = subprocess.run(  # noqa: S603 (configured binary, fixed argv)
            self.copy_args(src, dest),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RcloneError(f"rclone copy to {dest} failed: {result.stderr.strip()[:500]}")
        return result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
