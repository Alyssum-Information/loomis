# 06 · Configuration

| | |
|---|---|
| **Document** | Configuration Reference |
| **Doc ID** | LM-06 |
| **Version** | 0.1 (Draft) |
| **Last updated** | 2026-06-06 |
| **Related** | [05 Data Model](05-data-model-and-storage.md), [09 Security & Privacy](09-security-and-privacy-model.md), [features/](features/) |
| **Traces** | FR-9.1, FR-9.2, FR-7.8, NFR-1, NFR-9 |

---

Loomis is configured by a single **TOML file** with **environment-variable
overrides** ([FR-9.1](03-requirements-specification.md#fr-9-configuration--data-management)).
Defaults are **local-first**: a fresh config performs no network egress.

- Config file: `<data_dir>/config.toml` (path overridable via `LOOMIS_CONFIG`).
- Env override pattern: `LOOMIS_<SECTION>__<KEY>` (double underscore nests),
  e.g. `LOOMIS_LLM__PROVIDER=ollama`.
- Starter file ships as [`config.example.toml`](../config.example.toml).
- Settings loaded/validated with `pydantic-settings`; invalid values fail fast.

## 1. Precedence

`environment variables` > `config.toml` > `built-in defaults`.

## 2. Reference

```toml
[core]
data_dir = "~/.loomis"          # root for db, library, transcripts, logs
log_level = "INFO"
timezone  = "local"             # used for "calendar day" diary grouping

[api]                           # backend REST/WebSocket server (FastAPI)
host = "127.0.0.1"              # 0.0.0.0 exposes on LAN (opt-in, requires token)
port = 8080
# token read from env when LAN-exposed, never stored here:
#   LOOMIS_API__TOKEN=...
cors_origins = []               # extra allowed origins, e.g. the Vite dev server
serve_spa = true                # backend serves the built web/ SPA at "/"
open_browser = true

[backup]
poll_interval_s = 3
staging_dir = "staging"
verify_hash = "sha256"          # integrity gate before any source deletion
auto_delete_after_backup = false
transcode_policy = "keep_original"   # keep_original | transcode_keep | transcode_only

[transcode]
codec = "opus"
bitrate = "16k"
application = "voip"
ffmpeg_path = "ffmpeg"

[stt]
engine = "whisperx"             # whisperx (default) | null  (null = offline stub, no transcript)
model = "large-v3"
device = "auto"                 # auto | cuda | cpu
compute_type = "auto"
language = "auto"               # auto-detect; or force e.g. "zh"
# whisperx needs ffmpeg on PATH to read audio. ffmpeg + whisperx are installed by
# the repo-root install script (./install.ps1 / ./install.sh) — they are baseline,
# not optional. Use engine = "null" only to run the pipeline without transcription.
# device = "auto" uses an NVIDIA GPU when present. The default install ships CUDA
# PyTorch (the installer's `gpu` extra); pass -Cpu / --cpu for the CPU-only build.
# On CPU-only machines, use model = "small" or "medium" for a usable speed.

[jobs]                          # durable pipeline job runner (04 §7)
concurrency = 1                 # GPU-heavy steps serialize by default
poll_interval_s = 1.0
max_attempts = 3                # attempts beyond this park the job (dead-letter)
lease_seconds = 1800           # reclaim a 'running' job idle longer than this; must
                                # exceed the slowest step (no heartbeat yet)

[diarize]
engine = "pyannote"             # pyannote (default) | null
model = "pyannote/speaker-diarization-3.1"
device = "auto"                 # auto | cuda | cpu
min_speakers = 0                # 0 / unset = auto
max_speakers = 0
# pyannote's model is GATED: create a free HuggingFace token, accept the terms at
# https://huggingface.co/pyannote/speaker-diarization-3.1, then set it here (or via
# LOOMIS_DIARIZE__HF_TOKEN). Without it the diarize step parks.
hf_token = ""

[speaker_id]
engine = "pyannote"             # pyannote (default) | null
match_threshold = 0.70
margin = 0.10
new_identity_below = 0.55
vector_backend = "memory"       # memory | sqlite-vec

[llm]
provider = "ollama"             # ollama (default) | null  (cloud providers: future, opt-in)
model = "qwen2.5:7b"            # pulled by the install script; `ollama pull <model>` for others
host = "http://127.0.0.1:11434"
timeout_s = 120.0
max_retries = 2
# Ollama (+ this model) is baseline — the install script sets it up. Cloud API keys
# (future) come from env, never stored here or logged:  LOOMIS_LLM__API_KEY=...

[summaries]
diary_day_settle_minutes = 30
ambiguous_bias = "diary"
solo_dominance = 0.85
classify_confidence_floor = 0.6
summary_language = "auto"

[cloud]
enabled = false                 # opt-in; nothing leaves the machine until true
rclone_path = "rclone"
schedule_cron = ""              # empty = manual only
[[cloud.remotes]]
name = "onedrive"
scope = ["audio", "markdown"]   # audio | markdown | db
direction = "push"              # push-only; never deletes local
```

## 3. Security-sensitive settings

- **Cloud LLM API keys** and **rclone credentials** come from the environment /
  rclone's own config — **never** committed, **never** logged
  ([NFR-9](03-requirements-specification.md#2-non-functional-requirements)).
- `[api].host = "0.0.0.0"` or `[cloud].enabled = true` cross the privacy
  boundary; the UI surfaces this
  ([FR-7.8](03-requirements-specification.md#fr-7-user-interface)). See
  [09 Security & Privacy](09-security-and-privacy-model.md).

## 4. Per-device overrides

`auto_delete_after_backup` and `transcode_policy` can be set globally here and
overridden per device in that device's
[`device.json`](05-data-model-and-storage.md#2-on-device-registration-file--devicejson).
The device value wins.
