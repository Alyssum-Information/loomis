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
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
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
    # Run the background daemon (job runner + device watcher) inside the API process.
    # On by default for `serve`/`up`; tests disable it to stay deterministic/offline.
    run_daemon: bool = True


# Default match patterns when neither the device nor config narrows them.
_DEFAULT_AUDIO_GLOBS = ["**/*.wav", "**/*.mp3", "**/*.m4a", "**/*.flac", "**/*.ogg"]


class BackupSettings(BaseModel):
    """Source-watch + safety-spine import policy (see docs/features/01)."""

    poll_interval_s: float = 3.0  # USB volume poll cadence
    folder_poll_interval_s: float = 60.0  # watched-folder scan cadence (FR-1.12)
    # Import a folder file only once its mtime has been quiet this long, so a sync
    # tool's in-flight write is never half-imported (ADR-0012).
    folder_settle_seconds: float = 10.0
    staging_dir: str = "staging"  # relative to data_dir
    verify_hash: Literal["sha256"] = "sha256"  # integrity gate; only sha256 is supported
    auto_delete_after_backup: bool = False  # global default; device.json may override
    # Default: keep only the validated Opus in the library (ADR-0013) — ~10× smaller,
    # browser-playable, and a negligible STT cost at 32 kbps. keep_original /
    # transcode_keep remain available globally and per source (FR-3.4).
    transcode_policy: TranscodePolicy = TranscodePolicy.TRANSCODE_ONLY
    audio_globs: list[str] = Field(default_factory=lambda: list(_DEFAULT_AUDIO_GLOBS))


class SttSettings(BaseModel):
    """Speech-to-text engine selection (see docs/features/03, ADR-0002)."""

    engine: str = "whisperx"  # whisperx | null (null = offline/dev stub, no GPU deps)
    model: str = "large-v3"
    device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "auto"  # auto | float16 | int8 | ...
    # Whisper detects the language from the first ~30 s of each file, so clips that
    # open with silence/noise misdetect easily. Set your daily language (e.g. "zh")
    # unless you genuinely record in many languages (feature 03 §3).
    language: str = "auto"  # auto-detect, or force e.g. "zh"


class DiarizeSettings(BaseModel):
    """Speaker diarization engine selection (see docs/features/04, ADR-0007)."""

    engine: str = "pyannote"  # pyannote | null (null = offline/dev stub, no GPU deps)
    model: str = "pyannote/speaker-diarization-3.1"
    hf_token: str | None = None  # HuggingFace token for the gated pyannote model
    device: str = "auto"  # auto | cuda | cpu
    min_speakers: int | None = None  # hint; None lets pyannote decide
    max_speakers: int | None = None


class SpeakerIdSettings(BaseModel):
    """Voiceprint embedding + cross-recording matching (see docs/features/04 §4–5)."""

    engine: str = "pyannote"  # pyannote | null
    model: str = "pyannote/embedding"
    device: str = "auto"
    # Conservative defaults: prefer a new provisional identity over a wrong merge (§5).
    match_threshold: float = 0.70  # cosine ≥ this (with margin) → assign to existing
    margin: float = 0.10  # best must beat runner-up by this to assign confidently
    new_identity_below: float = 0.55  # best < this → create a new provisional identity
    vector_backend: str = "memory"  # memory (brute-force cosine) | sqlite-vec (future, §8)


class LlmSettings(BaseModel):
    """LLM provider for summaries + classification (see ADR-0005). Local-first default.

    Cloud providers are opt-in and send transcripts off-device (FR-7.8); their API
    keys come from the environment only, never config (NFR-9).
    """

    provider: str = "ollama"  # ollama | null (null = offline stub, no network)
    # qwen2.5:7b: strong, recent, runs on a typical consumer PC, and notably good at
    # Chinese/multilingual — a fit for Loomis's Mandarin-first transcripts.
    model: str = "qwen2.5:7b"
    host: str = "http://127.0.0.1:11434"  # Ollama endpoint
    timeout_s: float = 120.0
    max_retries: int = 2  # structured-output validation retries before giving up


class SummariesSettings(BaseModel):
    """Diary/meeting classification + aggregation policy (see docs/features/05)."""

    ambiguous_bias: str = "diary"  # tie-break: a stray meeting in the diary is cheaper
    solo_dominance: float = 0.85  # owner duration fraction above which multi-speaker → diary
    classify_confidence_floor: float = 0.6  # below this, ask the LLM to confirm
    # Quiet period after a day's last import before its diary is aggregated; the
    # daemon scheduler enforces this (one LLM pass per settled day, feature 05 §3).
    diary_day_settle_minutes: int = 30
    summary_language: str = "auto"  # auto = follow the transcript's dominant language


class TranscodeSettings(BaseModel):
    """Opus transcode parameters (see docs/features/02, ADR-0008/0013)."""

    codec: str = "opus"
    # 32k: speech stays clear and Whisper WER is near-uncompressed; below ~24k the
    # transcription cost starts to show (ADR-0013). ~14 MB/hour mono.
    bitrate: str = "32k"
    application: str = "voip"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"


SyncScope = Literal["audio", "markdown", "db"]


def _default_scope() -> list[SyncScope]:
    return ["audio", "markdown"]


class CloudRemote(BaseModel):
    """One rclone remote to push to (see docs/features/06, ADR-0004).

    ``name`` must match a remote configured via ``rclone config``; credentials
    live in rclone's own config, never here (NFR-9).
    """

    name: str
    scope: list[SyncScope] = Field(default_factory=_default_scope)
    direction: Literal["push"] = "push"  # push-only in v1; never deletes local (FR-8.4)
    dest: str = "loomis"  # path prefix on the remote


class CloudSettings(BaseModel):
    """Opt-in cloud sync (FR-8). Nothing leaves the machine while ``enabled`` is false."""

    enabled: bool = False
    rclone_path: str = "rclone"
    schedule_cron: str = ""  # empty = manual only; the daemon scheduler consumes this
    remotes: list[CloudRemote] = Field(default_factory=list)


class JobsSettings(BaseModel):
    """Durable job runner: pool size, polling, retry, and crash-reclaim policy."""

    concurrency: int = 1  # GPU-heavy steps serialize by default (04 §7)
    poll_interval_s: float = 1.0
    max_attempts: int = 3  # attempts beyond this park the job (dead-letter)
    # A 'running' job idle longer than this is treated as crashed and reclaimed.
    # No heartbeat yet, so this MUST exceed the slowest step (CPU STT can be minutes).
    lease_seconds: int = 1800


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
    stt: SttSettings = Field(default_factory=SttSettings)
    diarize: DiarizeSettings = Field(default_factory=DiarizeSettings)
    speaker_id: SpeakerIdSettings = Field(default_factory=SpeakerIdSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    summaries: SummariesSettings = Field(default_factory=SummariesSettings)
    transcode: TranscodeSettings = Field(default_factory=TranscodeSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)
    cloud: CloudSettings = Field(default_factory=CloudSettings)

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


# --- runtime settings editing (FR-7.7) ---

# Sections the API may edit. Anything else in a patch is rejected.
EDITABLE_SECTIONS = frozenset(
    {
        "core",
        "api",
        "backup",
        "stt",
        "diarize",
        "speaker_id",
        "llm",
        "summaries",
        "transcode",
        "jobs",
        "cloud",
    }
)

# Per-section keys that must never pass through the API. api.token is env-only by
# design (11 §2); run_daemon is a deployment/test switch, not a user setting.
BLOCKED_KEYS: dict[str, frozenset[str]] = {
    "api": frozenset({"token", "run_daemon"}),
}

# Changes to these need a process restart to take effect (bind address, thread
# pool size, …); the PATCH response flags them so the UI can say so.
RESTART_REQUIRED_KEYS = frozenset(
    {
        "core.data_dir",
        "api.host",
        "api.port",
        "api.serve_spa",
        "api.open_browser",
        "api.cors_origins",
        "jobs.concurrency",
    }
)

SECRET_MASK = "********"  # noqa: S105 (a display placeholder, not a credential)


def config_file_for(settings: Settings) -> Path:
    """Where settings edits persist: ``LOOMIS_CONFIG``, else ``<data_dir>/config.toml``.

    Derived from the *live* settings (not raw env) so tests and embedded use write
    where the data actually lives.
    """
    override = os.environ.get("LOOMIS_CONFIG")
    if override:
        return Path(override).expanduser()
    return settings.core.resolved_data_dir / "config.toml"


def validate_settings_patch(settings: Settings, patch: dict[str, Any]) -> list[str]:
    """Check a partial settings update; returns the list of ``section.key`` changed.

    Raises ``ValueError`` for unknown sections/keys, blocked keys, or values the
    section model rejects. Masked secret values are treated as "unchanged" and
    dropped from the patch (mutates ``patch``).
    """
    changed: list[str] = []
    for section, values in list(patch.items()):
        if section not in EDITABLE_SECTIONS:
            raise ValueError(f"unknown settings section: {section!r}")
        if not isinstance(values, dict):
            raise ValueError(f"section {section!r} must be an object")
        current = getattr(settings, section)
        for key, value in list(values.items()):
            if key not in type(current).model_fields:
                raise ValueError(f"unknown setting: {section}.{key}")
            if key in BLOCKED_KEYS.get(section, frozenset()):
                raise ValueError(f"setting {section}.{key} cannot be changed via the API")
            if value == SECRET_MASK:  # the UI echoed a masked secret back: no change
                del values[key]
                continue
            changed.append(f"{section}.{key}")
        # Validate the merged section so bad values fail before anything persists.
        merged = {**current.model_dump(mode="json"), **values}
        try:
            type(current).model_validate(merged)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(part) for part in first["loc"])
            raise ValueError(f"invalid value for {section}.{loc}: {first['msg']}") from exc
        if not values:
            del patch[section]
    return changed


def apply_settings_patch(settings: Settings, patch: dict[str, Any]) -> None:
    """Persist a validated patch to ``config.toml`` and apply it to the live object.

    File write first (durable), then in-place section replacement — every holder
    of the root ``Settings`` (daemon, runner, scheduler, request handlers) sees
    the new values immediately. Env overrides still win on the next full reload,
    matching the documented precedence (06 §1).
    """
    import tomllib

    import tomli_w

    path = config_file_for(settings)
    existing: dict[str, Any] = {}
    if path.is_file():
        existing = tomllib.loads(path.read_text(encoding="utf-8"))
    for section, values in patch.items():
        existing.setdefault(section, {})
        existing[section].update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(existing), encoding="utf-8")

    for section, values in patch.items():
        current = getattr(settings, section)
        merged = {**current.model_dump(mode="json"), **values}
        setattr(settings, section, type(current).model_validate(merged))
