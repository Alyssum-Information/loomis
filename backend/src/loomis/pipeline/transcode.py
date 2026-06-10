"""Optional Opus transcode via ffmpeg (FR-3.1–3.3, ADR-0008).

Wraps the ffmpeg/ffprobe binaries. The output is **validated** (it must decode and
have a plausible duration) before any caller deletes an original under the
``transcode_only`` policy — the transcode leg of the safety spine (02 §4).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..core.config import TranscodeSettings


class TranscodeError(RuntimeError):
    """Raised when ffmpeg fails or the produced file fails validation."""


class Transcoder:
    def __init__(self, settings: TranscodeSettings) -> None:
        self._s = settings

    def available(self) -> bool:
        return shutil.which(self._s.ffmpeg_path) is not None

    def probe_duration(self, path: Path) -> float | None:
        """Seconds via ffprobe, or None if it can't be determined."""
        if shutil.which(self._s.ffprobe_path) is None:
            return None
        out = subprocess.run(  # noqa: S603 (configured binary, fixed argv)
            [
                self._s.ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            return None
        try:
            value = json.loads(out.stdout)["format"]["duration"]
            return float(value)
        except (KeyError, ValueError, json.JSONDecodeError):
            return None

    def to_opus(self, src: Path, dst: Path) -> None:
        """Transcode ``src`` → ``dst`` (Opus). Raises :class:`TranscodeError` on failure."""
        if not self.available():
            raise TranscodeError(f"ffmpeg not found on PATH ({self._s.ffmpeg_path})")
        if src.resolve() == dst.resolve():
            # ffmpeg -y would read and overwrite the same file → corruption. Never.
            raise TranscodeError(f"transcode source and destination are the same file: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(  # noqa: S603 (configured binary, fixed argv)
            [
                self._s.ffmpeg_path,
                "-y",
                "-i",
                str(src),
                "-c:a",
                "libopus",
                "-b:a",
                self._s.bitrate,
                "-application",
                self._s.application,
                str(dst),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise TranscodeError(f"ffmpeg failed for {src}: {result.stderr.strip()[:500]}")

    def validate(self, path: Path, *, expected_duration: float | None = None) -> bool:
        """True iff the file exists, decodes (has a duration), and matches expectation.

        With ``expected_duration`` set, the decoded duration must be within 1s or 5%.
        Gate for source deletion under ``transcode_only`` (FR-3.3).
        """
        if not path.exists() or path.stat().st_size == 0:
            return False
        duration = self.probe_duration(path)
        if duration is None or duration <= 0:
            return False
        if expected_duration is not None and expected_duration > 0:
            tolerance = max(1.0, expected_duration * 0.05)
            if abs(duration - expected_duration) > tolerance:
                return False
        return True
