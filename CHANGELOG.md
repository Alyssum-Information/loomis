# Changelog

All notable changes to this project will be documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Notes
- M1 import runs as a CLI process. Until the background daemon lands, avoid
  running `loomis backup` and the API server against the same database
  concurrently (single-writer assumption).
- The pipeline runs via `loomis worker`; WhisperX is an opt-in extra
  (`uv sync --extra stt`) and needs ffmpeg on PATH for transcode.

_See the [roadmap](docs/08-roadmap-and-milestones.md) for what's next (M2: local intelligence — speakers + summaries)._
