# Changelog

All notable changes to this project will be documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **M4 folder sources** (FR-1.11–1.13, ADR-0012): any local folder — a phone's
  Syncthing/OneDrive/iCloud sync target, a lifelogger's export folder, a manual
  drop folder — registers as a first-class source beside USB recorders. The
  daemon polls registered folders (`[backup].folder_poll_interval_s`) through
  the identical SHA-256 safety spine; a settle window
  (`[backup].folder_settle_seconds`) keeps half-synced files out of the library;
  folder sources never auto-delete by default. `loomis backup <path>` and
  `POST /devices/register` auto-detect the source kind (removable volume → usb,
  else folder); the Devices screen becomes **Sources** with an "Add source"
  flow and per-folder watched-path display. Schema migration 008 adds
  `devices.kind` / `devices.source_path`.
- **M4 speaker name suggestions** (FR-5.8): the diary/meeting prompts (now
  versioned **v2**) also extract names for unnamed speakers from conversational
  evidence (being addressed by name, self-introductions). Proposals are stored
  as `speakers.suggested_name` (+ `needs_review`) — never applied silently —
  and surface in the Speakers screen as a one-click **Accept** chip; accepting
  (or any manual rename) clears the suggestion. New `speaker.updated` WebSocket
  event. Migration 008 adds the column.
- **Re-transcription endpoints** (FR-4.2): `POST /recordings/{id}/retranscribe`
  (surfaced as a **Re-transcribe** button on the Recording page) and bulk
  `POST /recordings/retranscribe` with a detected-language filter
  (`{"not_language": "zh"}` re-runs every misdetected file). STT re-runs
  idempotently and rebuilds everything downstream — diarization, speaker
  identity, and the affected days' diaries/meetings.

### Changed
- **Transcode to Opus by default** (FR-3.1, ADR-0013): new imports are now
  transcoded to validated 32 kbps Opus (`voip`) and the library original is
  replaced — ~10× smaller, browser-playable (no preview cache for new imports),
  and ≈0–2 % relative WER cost per published measurements (degradation only
  appears below ~24 kbps, hence the bitrate bump from 16k). The safety spine is
  unchanged: deletion still requires a decoded, duration-checked Opus, and the
  job parks instead of deleting when ffprobe is unavailable. Bit-exact archives
  remain one setting away: `transcode_keep` / `keep_original`, globally
  (`[backup].transcode_policy`) or per source (`device.json`).
- **STT language guidance** (FR-4.2): Whisper detects the language from the
  first ~30 s of each file, so clips opening with silence/noise misdetect
  easily. `[stt].language` (e.g. `"zh"`) is now the documented, recommended
  setting for single-language users — faster and immune to misdetection;
  config reference, example config, and feature 03 updated. Preprocessing
  (VAD/segmentation, resampling, denoise, loudness) was evaluated: WhisperX
  already runs pyannote VAD and 16 kHz mono normalization internally; denoise
  and loudness normalization measured neutral-to-harmful and stay out of the
  default path (feature 03 §3.1).
- **Backend restructured into packages** matching the architecture doc
  (04 §12): `core/` (config, db, models, repository, storage, events, vectors),
  `ingest/` (watcher, devicefile, backup), `pipeline/` (runner, steps, and the
  step engines), `api/` (app, routes, schemas), with `cli.py` / `daemon.py` /
  `launcher.py` at the top level. Pipeline read-models moved to `core.models`
  and vector math to `core.vectors` so `core` has no upward dependencies. No
  behavior change; the uvicorn factory is now `loomis.api.app:create_app`.

### Added
- **Record-centric pipeline view** (FR-7.6): new `GET /api/v1/pipeline` returns one row
  per recording with its stage states — **備份 backup** (the safety-spine import),
  **語音轉文字 STT** (transcript readiness: transcode/stt), and **摘要 summary** (the
  post-transcript work: diarize/speaker_id/classify/diary_aggregate/meeting_extract).
  A stage is `done` (green) when complete, `active` (blue) only while a job is actually
  running, `failed` when a job parked, else `pending` (grey — not started or queued).
  The failed stage exposes its retryable `job_id`. The web
  **Jobs** screen is replaced by a per-recording **Records** screen (`/records`) showing
  a backup → STT → summary progress per recording (was a raw per-job table).
- **`install.sh` / `install.ps1`** at the repo root: one command installs **all
  baseline requirements** for the full pipeline — uv, Node + pnpm, ffmpeg, Ollama
  (+ the default model), and the backend STT/diarize/LLM extras + web deps — so
  `uv run loomis up` works without manual setup. ffmpeg and the WhisperX/pyannote/
  Ollama backends are baseline, not optional; only *alternative* backends are.
  (`--skip-llm-model` / `-SkipLlmModel` skips the large Ollama pull. Diarization
  still needs a one-time HuggingFace token for pyannote's gated model — see README.)
- **Bulk job retry**: `POST /api/v1/jobs/retry-all` requeues every failed/parked job;
  the Jobs screen gains a **Retry all** button.
- `loomis check` now reports whether the optional `whisperx` / `pyannote` Python
  modules are importable.

### Fixed
- **Recording playback for recorder codecs** (FR-7.3): many voice recorders write
  ADPCM/A-law inside `.wav`, which no browser can decode — the Recording page's
  player silently failed. `GET /recordings/{id}/audio` now probes the codec and,
  when the browser can't play it, decodes the file once (near-instant) into a
  PCM preview under `<data_dir>/cache/preview/` and serves that, keeping HTTP
  Range (seeking) intact. Explicit `audio/*` content types per extension.
- **Transcript follows playback** (FR-7.3): the Recording page highlights the
  line under the playhead, auto-scrolls to keep it visible, and every line gets
  a play/pause button that seeks to its timestamp (clicking the row still seeks).
- **speaker_id no longer needs torchcodec**: the pyannote embedder now decodes audio
  with whisperx's ffmpeg CLI and hands pyannote an in-memory `{waveform, sample_rate}`
  dict instead of a file path. File-path decoding routed through torchcodec, whose
  Windows DLLs frequently fail to load (mismatched ffmpeg shared libs) — parking the
  `speaker_id` step. STT and diarization already used the in-memory path. The harmless
  torchcodec import warning is also muted.

### Changed
- **GPU PyTorch by default**: the installer now installs the **CUDA** torch build.
  New mutually-exclusive `gpu` / `cpu` extras pin torch/torchaudio to the PyTorch
  CUDA (cu128) or CPU wheel index in the universal lockfile (`[tool.uv.sources]` +
  `[tool.uv].conflicts`), so `uv sync --extra gpu` records the CUDA build once and
  later `uv run` keeps it — no `UV_TORCH_BACKEND` env var or post-sync overlay.
  `install.ps1` / `install.sh` select `gpu` by default, `-Cpu` / `--cpu` for the
  smaller CPU-only wheels. whisperx stays at its current version (torch 2.8 cu128
  wheels satisfy it).
- **Permanent failures park immediately**: a missing optional dependency (e.g.
  `whisperx`) or a bad engine/provider name now parks the job on the first attempt
  with an actionable message (run `./install.sh`) instead of burning the full retry
  budget. Engine/provider construction raises a typed `PermanentJobError`.
- **Opt-in device registration** (FR-1.3, 1.9, 1.10): the daemon no longer
  auto-registers or imports every connected volume. It imports **only registered
  devices**; an unregistered volume raises a prompt (`device.connected` with
  `registered:false`) and nothing is written to it. Registration is an explicit
  user action — `POST /devices/register` (Devices screen) writes `device.json` and
  activates the row. New `DELETE /devices/{id}` unregisters a device (removes
  `device.json` when reachable, deactivates the row; recordings are retained).
  Schema migration 007 adds `devices.registered`. The standalone `loomis backup`
  CLI still registers the volume you explicitly target.

### Added
- **M3 daemon foundation**: `loomis serve` / `loomis up` now run the durable job
  runner and the device watcher as background threads inside the API process, so a
  single process is the only SQLite writer. An in-process event bus carries
  `job.updated` / `device.connected` / `recording.added` events (the WebSocket that
  relays them to the UI lands next). Opt-out via `[api].run_daemon` (off in tests).
  The standalone `loomis worker` / `loomis backup` CLIs remain for headless use.
- **M3 REST read API** (FR-7.2–7.6, 11 §3): read-only `/api/v1` endpoints for
  devices (incl. `pending`), recordings + transcripts + audio streaming (HTTP Range),
  timeline, diary, meetings, speakers, jobs, and full-text `search` (FTS5, maintained
  from the repository layer — migration 006). Cursor pagination, a normalized
  `{"error": {code, message}}` envelope, and an auto-published OpenAPI schema (the
  basis for the frontend's typed client).
- **M3 WebSocket** (FR-7.6, 11 §4): `/api/v1/ws` relays in-process bus events to the
  SPA — `job.updated`, `device.connected`, `recording.added`, and `diary.updated`
  (emitted by the diary aggregation step) — so the UI reflects backend state without
  polling.
- **M3 command endpoints** (FR-1.7, 5.5, 6.8, 7.6, 11 §3): writes that mutate the
  library — `POST /devices/register`, `PATCH /devices/{id}`, `PATCH /speakers/{id}`
  (rename/confirm) — plus heavy actions that return `202 Accepted` with a `job_id`:
  `POST /speakers/merge`, `POST /speakers/{id}/split`, `POST /diary/{date}/resummarize`,
  `POST /jobs/{id}/retry`. Speaker merge/split run as durable pipeline jobs
  (`speaker_merge` / `speaker_split`).
- **M3 web UI — read screens** (FR-7.2, 7.3, 7.5, 7.6): the Vue 3 + Vuetify SPA gains
  a navigation shell with a live-connection indicator and read-only screens —
  Dashboard, Timeline, Recording detail (audio player with click-to-seek transcript),
  Diary, Meeting, Search, and Jobs — over a typed API client and a WebSocket store
  that refreshes views from `job.updated` / `recording.added` / `diary.updated` events.
- **M3 web UI — management screens** (FR-1.3, 1.7, 5.5, 7.6): a Speakers screen
  (rename, confirm, merge, split), a Devices screen (register pending volumes, edit
  per-device settings) with a new-device prompt driven by `device.connected`, and a
  Retry action on the Jobs screen — completing the browsable-product milestone (M3).

## [0.2.0] - 2026-06-09

First tagged pre-alpha: the ingest spine (M1) plus local intelligence (M2) —
diarization, cross-recording speaker identity, and diary/meeting summaries.

### Added
- Project design and documentation: vision, user flows, requirements,
  architecture, data model, configuration, API specification, the six feature
  specs (`docs/features/`), UI/UX, roadmap, security & privacy model, and glossary.
- Architecture Decision Records (`docs/adr/`): STT (WhisperX), frontend + API
  (Vue + Vuetify SPA over FastAPI), cloud backend (rclone), LLM strategy (Ollama
  default, pluggable), database (SQLite), diarization (pyannote), audio
  compression (Opus), device registration format, Python tooling, USB detection.
- Project files: README, example configuration, and backend project metadata
  skeleton.
- **Walking skeleton:** typed config (`pydantic-settings`), SQLite + a versioned
  migration runner, FastAPI `GET /api/v1/health`, and the Vue + Vuetify SPA wired
  to it over the Vite dev proxy.
- **One-click launcher:** `loomis up` (default) starts the backend + Vite together
  with multiplexed logs, health-wait, and child-only shutdown; `loomis check`
  reports prerequisites; `--prod` builds and serves the SPA from the backend.
- **M1 safe ingest — backup core** (FR-1.1–1.6, FR-2.1–2.8): device detection (psutil poll) and
  registration via `<volume>/.loomis/device.json`; the SHA-256 safety-spine import
  (copy → verify → dedupe → commit → optional gated source delete); a per-device
  free-space guard; failed copies recorded in a `quarantine` table; orphaned
  staging files swept at the start of each run; structured logging. CLI:
  `loomis backup [VOLUME] [--watch] [--name] [--auto-delete]`.

- **M1 safe ingest — transcription pipeline** (FR-3.1–3.4, FR-4.1–4.5): a durable SQLite job
  runner (atomic claim, retry → park, crash-reclaim by lease) with a bounded
  worker pool; a swappable `STTEngine` (WhisperX with GPU/CPU auto + lazy load,
  plus a dep-free `null` engine for offline/CI); transcript + time-aligned segment
  persistence (`transcripts/<id>.json` + DB, one per recording, idempotent); and
  optional Opus transcode with decode/duration validation gating source deletion.
  CLI: `loomis worker [--once] [--types ...]`.

- **M2 speakers — diarization + identification** (FR-5.1–5.4): the pipeline extends
  `stt → diarize → speaker_id`. Swappable, lazy-loaded `pyannote` diarize + embedding
  engines (dep-free `null` engines for offline/CI); a voiceprint DB (`speakers`,
  `voiceprints`) with in-memory cosine matching that assigns to an existing identity,
  creates a new provisional one, or flags uncertain matches for review; per-segment
  speaker labels; idempotent `speaker_id` re-runs.

- **M2 summaries — diary + meetings** (FR-6.1–6.9): the pipeline completes
  `speaker_id → classify → {diary_aggregate | meeting_extract} → link`. Heuristic
  diary-vs-meeting classification with optional LLM confirmation; a pluggable
  `LLMProvider` (Ollama default, dep-free `null` for offline/CI) with
  schema-validated, retried structured output; first-person daily diary aggregation
  per local day and standalone meeting records with attendees/decisions/action items;
  Markdown + JSON sidecars under `diary/` and `meetings/`, with day→meeting back-links.
  New tables: `diary_entries`, `meetings`, and their join/link tables. Idempotent
  re-aggregation and re-extraction.

### Notes
- M1 import runs as a CLI process. Until the background daemon lands, avoid
  running `loomis backup` and the API server against the same database
  concurrently (single-writer assumption).
- The pipeline runs via `loomis worker`; WhisperX is an opt-in extra
  (`uv sync --extra stt`) and needs ffmpeg on PATH for transcode.

_See the [roadmap](docs/08-roadmap-and-milestones.md) for what's next (M3: browsable product — REST/WebSocket API + Vue UI)._
