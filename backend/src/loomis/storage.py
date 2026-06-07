"""On-disk layout + content hashing (the bytes side of the data model).

The DB holds metadata; bulk audio lives under ``<data_dir>/`` in the layout from
../../docs/05-data-model-and-storage.md §1. ``Workspace`` resolves those paths and
``sha256_file`` is the integrity primitive for the safety spine
([04 §8](../../docs/04-system-architecture.md)).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_CHUNK = 1024 * 1024  # 1 MiB streaming reads keep large files off the heap
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def sha256_file(path: Path) -> str:
    """Stream a file through SHA-256; returns the lowercase hex digest."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def slugify(name: str) -> str:
    """Filesystem-safe device slug for library paths (``Sony ICD-TX660`` → ``sony-icd-tx660``)."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "device"


@dataclass(slots=True)
class Workspace:
    """Resolves and creates the on-disk directories under ``data_dir``."""

    data_dir: Path

    @property
    def staging(self) -> Path:
        return self.data_dir / "staging"

    @property
    def quarantine(self) -> Path:
        return self.data_dir / "quarantine"

    @property
    def library(self) -> Path:
        return self.data_dir / "library"

    def ensure(self) -> None:
        for d in (self.staging, self.quarantine, self.library):
            d.mkdir(parents=True, exist_ok=True)

    def library_path(
        self, device_slug: str, recorded_at: datetime, recording_id: str, ext: str
    ) -> Path:
        """``library/<slug>/<YYYY>/<MM>/<recording_id><ext>`` — grouped by capture month."""
        return (
            self.library
            / device_slug
            / f"{recorded_at:%Y}"
            / f"{recorded_at:%m}"
            / f"{recording_id}{ext}"
        )
