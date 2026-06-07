"""Typed configuration for the Loomis backend.

Local-first defaults: nothing here causes network egress. Values come from
built-in defaults, then an optional TOML file, then environment variables
(``LOOMIS_<SECTION>__<KEY>``) — see ../../docs/06-configuration.md.

Only the sections implemented so far (``core``, ``api``, ``backup``) are modelled;
more are added as features land.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from .models import TranscodePolicy


def _config_path() -> Path:
    """Resolve the TOML config path: ``LOOMIS_CONFIG`` env, else data dir default."""
    override = os.environ.get("LOOMIS_CONFIG")
    if override:
        return Path(override).expanduser()
    data_dir = os.environ.get("LOOMIS_CORE__DATA_DIR", "~/.loomis")
    return Path(data_dir).expanduser() / "config.toml"


class CoreSettings(BaseModel):
    data_dir: Path = Field(default=Path("~/.loomis"))
    log_level: str = "INFO"
    timezone: str = "local"

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser()


class ApiSettings(BaseModel):
    host: str = "127.0.0.1"  # 0.0.0.0 exposes on LAN (opt-in, needs token)
    port: int = 8080
    cors_origins: list[str] = Field(default_factory=list)
    serve_spa: bool = True
    open_browser: bool = True
    token: str | None = None  # required when LAN-exposed; from env only


# Default match patterns when neither the device nor config narrows them.
_DEFAULT_AUDIO_GLOBS = ["**/*.wav", "**/*.mp3", "**/*.m4a", "**/*.flac", "**/*.ogg"]


class BackupSettings(BaseModel):
    """Device-watch + safety-spine import policy (see docs/features/01)."""

    poll_interval_s: float = 3.0
    staging_dir: str = "staging"  # relative to data_dir
    verify_hash: Literal["sha256"] = "sha256"  # integrity gate; only sha256 is supported
    auto_delete_after_backup: bool = False  # global default; device.json may override
    # validated against the enum; a device.json may still override per device:
    transcode_policy: TranscodePolicy = TranscodePolicy.KEEP_ORIGINAL
    audio_globs: list[str] = Field(default_factory=lambda: list(_DEFAULT_AUDIO_GLOBS))


class Settings(BaseSettings):
    """Root settings object. Access via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="LOOMIS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    core: CoreSettings = Field(default_factory=CoreSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    backup: BackupSettings = Field(default_factory=BackupSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence (first wins): env > TOML file > defaults.
        toml = TomlConfigSettingsSource(settings_cls, toml_file=_config_path())
        return (env_settings, toml, init_settings)


def get_settings() -> Settings:
    """Load settings fresh (cheap; call once at startup and store on app state)."""
    return Settings()
