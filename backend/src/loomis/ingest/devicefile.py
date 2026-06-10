"""The on-device registration file — ``<volume>/.loomis/device.json``.

Schema and rationale: ../../docs/05-data-model-and-storage.md §2 and
[ADR-0009](../../docs/adr/0009-device-registration-format.md). Parsed (pydantic)
on every connect; unknown future keys are ignored so a newer writer stays
forward-compatible, and a hand-authored file validates the same way (FR-1.6).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..core.models import DeviceKind, TranscodePolicy

SCHEMA = "loomis.device/v1"
DEVICE_DIR = ".loomis"
DEVICE_FILE = "device.json"

_DEFAULT_GLOBS = ["**/*.wav", "**/*.mp3", "**/*.m4a"]


def device_file_path(volume: Path) -> Path:
    """Location of the registration file in a source root (volume or watched folder)."""
    return volume / DEVICE_DIR / DEVICE_FILE


class DeviceBackup(BaseModel):
    model_config = ConfigDict(extra="ignore")
    auto_delete_after_backup: bool = False
    min_free_bytes_guard: int = 0


class DeviceTranscode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    policy: TranscodePolicy = TranscodePolicy.KEEP_ORIGINAL
    codec: str = "opus"
    bitrate: str = "16k"
    application: str = "voip"


class DeviceFile(BaseModel):
    """Typed view of ``device.json``. Read defensively, write canonically."""

    # ``schema`` is a BaseModel attribute name, so store under ``schema_`` + alias.
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_: str = Field(default=SCHEMA, alias="schema")
    device_id: str
    kind: DeviceKind = DeviceKind.USB  # usb volume or watched folder (ADR-0012)
    name: str
    owner_speaker_hint: str | None = None
    registered_at: str
    loomis_version: str
    audio_globs: list[str] = Field(default_factory=lambda: list(_DEFAULT_GLOBS))
    backup: DeviceBackup = Field(default_factory=DeviceBackup)
    transcode: DeviceTranscode = Field(default_factory=DeviceTranscode)

    @classmethod
    def load(cls, path: Path) -> DeviceFile:
        """Parse + validate a ``device.json`` (raises on malformed JSON / schema)."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, path: Path) -> None:
        """Write canonical JSON (by alias, stable indent), creating ``.loomis/``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json", by_alias=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
