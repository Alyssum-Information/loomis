# Changelog

All notable changes to this project will be documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
