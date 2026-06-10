# 04 · System Architecture

| | |
|---|---|
| **Document** | System Architecture |
| **Doc ID** | LM-04 |
| **Version** | 0.2 (Draft) |
| **Last updated** | 2026-06-10 |
| **Related** | [03 SRS](03-requirements-specification.md), [05 Data Model](05-data-model-and-storage.md), [features/](features/), [adr/](adr/README.md) |
| **Traces** | NFR-1 … NFR-8 |

---

This document describes Loomis's components, how data flows through them, and the
cross-cutting concerns (concurrency, durability, privacy). It is the
"big-picture" companion to the [data model](05-data-model-and-storage.md) and the
[ADRs](adr/README.md), which justify each technology choice.

## 1. Design tenets

- **Local-first.** No component reaches the network in the default config.
- **Two long-lived processes, decoupled.** A headless **daemon** does the work;
  a **web UI** observes and controls it. They communicate only through SQLite
  and the file library, so either can restart without the other.
- **Durable job queue.** All heavy work is broken into retryable, idempotent
  job steps persisted in SQLite. Crashes resume; they don't corrupt.
- **Ports & adapters.** STT, LLM, and cloud are interfaces with swappable
  implementations chosen by config.

## 2. System context

```
 sources         ┌──────────────────────────────────────────────────────┐
 ┌────────────┐  │                     Loomis                            │
 │USB recorder│◀─┼─▶┌──────────────────────────┐     ┌────────────────┐  │
 ├────────────┤  │  │  backend/ (Python)       │     │  web/ (Vue SPA)│  │
 │watched     │  │  │  ┌────────┐ ┌─────────┐  │ REST│  Vuetify       │  │
 │folder      │◀─┼─▶│  │ Daemon │ │ FastAPI │◀─┼─────┼─ + WebSocket   │  │
 │(phone /    │  │  │  │(workers)│ │ REST/WS │  │     └────────────────┘  │
 │ lifelogger │  │  │  └────┬───┘ └────┬────┘  │                          │
 │ sync)      │  │  └───────┼──────────┼───────┘                          │
 └────────────┘  │  ┌───────▼──────────▼──────────────────────────────┐   │
                 │  │ SQLite DB  +  File library (audio/MD)            │   │
                 │  └───────┬─────────────────────────────────────────┘   │
                 └──────────┼──────────────────────────────────────────---┘
                            │ (opt-in only)
             ┌──────────────┼──────────────┐
             ▼                              ▼
    Ollama / cloud LLM            rclone → OneDrive / GDrive / …
```

The **backend** (Python, in `backend/`) hosts both the background daemon and a
**FastAPI** REST/WebSocket server over the shared SQLite DB + file library. The
**frontend** (`web/`) is a **Vue 3 + Vuetify** single-page app that talks to the
backend only over HTTP/WebSocket. See [ADR-0003](adr/0003-frontend-vue-spa.md)
and the [repository layout](#12-repository-layout).

## 3. Processes

### 3.1 Daemon (background workers)
Owns all side effects: watching sources (USB volumes **and** registered
folders), importing, transcoding, running the processing pipeline, and cloud
sync. Single writer to the file library. Internally: the **Source Watcher**
(volume connect events + folder polls), the **Job Runner** (worker pool), and
the **Scheduler** (cloud sync, diary "day-settled" debounce).

### 3.2 API server (FastAPI, Python — `backend/`)
A local HTTP server (default `127.0.0.1`, LAN-accessible only if the user opts
in) exposing the **REST + WebSocket** surface the frontend consumes: read
endpoints (timeline, recordings, transcripts, speakers, diaries, meetings,
search, job/health) and command endpoints (register device, rename/merge/split
speaker, "sync now", re-summarize). Heavy work is **not** done in request
handlers — commands enqueue jobs the daemon executes; a WebSocket pushes live
job/health/egress updates. The daemon and API run in one Python process by
default (shared DB + library) but can be split unchanged. Full surface:
[11 API Specification](11-api-specification.md).

### 3.3 Frontend SPA (Vue 3 + Vuetify — `web/`)
A static single-page app that talks to the backend **only** over HTTP/WebSocket.
It holds no business logic and never touches SQLite or the file library
directly. Built with Vite; in production the backend can serve the built assets,
in development a Vite dev server proxies to the API. See
[ADR-0003](adr/0003-frontend-vue-spa.md).

## 4. Components

| Component | Responsibility | Key deps | Feature spec |
|-----------|----------------|----------|--------------|
| **Source Watcher** | Detect volume connect/remove; poll registered folder sources; resolve registered source. | psutil + native events | [01](features/01-device-registration-and-backup.md) |
| **Source Registry** | Read/write `device.json` (volumes *and* folders); manage `devices` rows. | pydantic | [01](features/01-device-registration-and-backup.md) |
| **Backup/Ingest** | Enumerate, dedupe via ledger, copy, SHA-256 verify, optional source delete. | hashlib, shutil | [01](features/01-device-registration-and-backup.md) |
| **Transcoder** | Optional Opus transcode; validate output. | ffmpeg (libopus) | [02](features/02-audio-compression.md) |
| **Job Runner** | Pull jobs, execute pipeline steps, retry, record errors. | SQLite queue | [04 §6](#6-processing-pipeline) |
| **STT Adapter** | Transcript + word timestamps; language detect. | WhisperX | [03](features/03-transcription.md) |
| **Diarizer** | Speaker turns; per-turn embeddings. | pyannote 3.1 | [04](features/04-speaker-diarization-and-identification.md) |
| **Speaker ID** | Match/enroll voiceprints; cross-recording identity. | numpy / sqlite-vec | [04](features/04-speaker-diarization-and-identification.md) |
| **Classifier** | Diary-type vs meeting-type. | heuristics + LLM | [05](features/05-summarization-and-organization.md) |
| **LLM Adapter** | Diary & meeting summaries; structured output. | Ollama / cloud | [05](features/05-summarization-and-organization.md) |
| **Summary Writer** | Assemble daily diary; extract meetings; write Markdown. | templates | [05](features/05-summarization-and-organization.md) |
| **Cloud Sync** | Push library/docs to remotes. | rclone | [06](features/06-cloud-sync.md) |
| **API Server** | REST/WebSocket surface; enqueue commands, stream updates. | FastAPI, uvicorn | [11](11-api-specification.md) |
| **Web SPA** | Browse/search/manage; surface job health & egress. | Vue 3, Vuetify, Vite | [07](07-ui-ux-design.md) |
| **Config** | Load/validate TOML + env; expose typed settings. | pydantic-settings | [06](06-configuration.md) |
| **Storage/Migrations** | DB access, schema versioning. | sqlite3 | [05](05-data-model-and-storage.md) |

## 5. API surface

The frontend SPA consumes a local **REST + WebSocket** API served by the backend
(FastAPI), auto-documented via OpenAPI. REST for queries and commands; a
WebSocket channel for live job/health/egress push. Full endpoint list, payload
shapes, and auth model: [11 API Specification](11-api-specification.md).

## 6. Processing pipeline

Each imported recording flows through an ordered set of **job steps**. A step
reads its input from the DB/filesystem and writes its output back, then enqueues
the next step. Steps are idempotent: re-running a completed step is a no-op or a
safe overwrite.

```
import ─▶ transcode? ─▶ stt ─▶ diarize ─▶ speaker_id ─▶ classify
                                                           │
                                              ┌────────────┴────────────┐
                                              ▼                         ▼
                                       diary_aggregate           meeting_extract
                                              └─────────► link ◄────────┘
```

| Step | Input | Output | Spec |
|------|-------|--------|------|
| `transcode` | original audio | normalized/Opus audio + validity check | [02](features/02-audio-compression.md) |
| `stt` | audio | transcript + word-timestamped segments + language | [03](features/03-transcription.md) |
| `diarize` | audio + segments | speaker turns + per-turn embeddings | [04](features/04-speaker-diarization-and-identification.md) |
| `speaker_id` | embeddings | identity assignment (known or provisional) | [04](features/04-speaker-diarization-and-identification.md) |
| `classify` | transcript + diarization | `diary` or `meeting` + confidence | [05](features/05-summarization-and-organization.md) |
| `diary_aggregate` | day's diary-type recordings | daily diary entry | [05](features/05-summarization-and-organization.md) |
| `meeting_extract` | meeting-type recording(s) | meeting record + diary back-link | [05](features/05-summarization-and-organization.md) |

Diary aggregation is **day-scoped** and debounced (a "day-settled" timer plus
re-trigger on late arrivals).

## 7. Concurrency & durability model

- **Job queue in SQLite.** Steps are claimed atomically (status + attempt count +
  worker id) so a crashed worker's job is reclaimed, not lost. WAL mode for
  concurrent readers (UI) alongside the writer (daemon).
- **Bounded worker pool.** GPU-heavy steps (STT, diarize) are serialized/capped
  to avoid VRAM thrash; lightweight steps run more concurrently.
- **Single library writer.** Only the daemon mutates the file library.
- **Lazy model loading.** STT/diarization/LLM models load on first use and can
  unload when idle.

## 8. Data integrity (the safety spine)

1. Copy to staging → 2. compute SHA-256 → 3. compare against expected → 4. commit
to library + ledger → 5. *only then* (optionally) transcode-and-verify → 6.
*only then* (optionally) delete the source. A failure at any point leaves the
source intact and quarantines the partial copy. This ordering is the core
guarantee behind [NFR-2](03-requirements-specification.md#2-non-functional-requirements).

## 9. Storage layout (summary)

```
<data_dir>/
  loomis.db                # SQLite (metadata, transcripts, jobs, speakers)
  config.toml
  library/<device>/<YYYY>/<MM>/   # imported audio (original and/or .opus)
  transcripts/<recording_id>.json
  diary/<YYYY-MM-DD>.md
  meetings/<meeting_id>.md
  staging/                 # in-flight copies (pre-verification)
  quarantine/              # failed-verification copies
  logs/
```

Full schema and the `device.json` contract are in
[05 Data Model](05-data-model-and-storage.md).

## 10. Privacy & trust boundary

The dashed boundary in §2 is the only place data can leave the machine, and
**nothing crosses it by default**:

- **Cloud LLM** (optional): transcripts sent to the chosen provider only when
  explicitly enabled. See [ADR-0005](adr/0005-llm-provider-abstraction.md).
- **Cloud sync** (optional): files go to user-owned rclone remotes only when
  enabled. See [ADR-0004](adr/0004-cloud-backup-rclone.md).

The UI must show, per [FR-7.8](03-requirements-specification.md#fr-7-user-interface),
whenever a configured action will cross this boundary. Full model:
[09 Security & Privacy](09-security-and-privacy-model.md).

## 11. Key technology decisions

See the [ADR index](adr/README.md). Summary:

| Decision | Choice | ADR |
|----------|--------|-----|
| STT engine | WhisperX | [0002](adr/0002-stt-engine-whisperx.md) |
| Frontend + API | Vue 3 + Vuetify SPA over FastAPI | [0003](adr/0003-frontend-vue-spa.md) |
| Cloud backend | rclone | [0004](adr/0004-cloud-backup-rclone.md) |
| LLM | Ollama default, pluggable | [0005](adr/0005-llm-provider-abstraction.md) |
| Database | SQLite | [0006](adr/0006-database-sqlite.md) |
| Diarization | pyannote 3.1 | [0007](adr/0007-speaker-diarization-pyannote.md) |
| Audio codec | Opus (ffmpeg) | [0008](adr/0008-audio-compression-opus.md) |
| Device file | `.loomis/device.json` | [0009](adr/0009-device-registration-format.md) |
| Tooling (backend) | uv + ruff + mypy | [0010](adr/0010-python-tooling.md) |
| Device detection | poll + native events | [0011](adr/0011-usb-device-detection.md) |

## 12. Repository layout

A monorepo with a clear backend/frontend split:

Backend packages follow the four architecture roles (not one package per
feature — most features are a single module, and the pipeline reads best as one
ordered package):

```
loomis/
  backend/                 # Python backend
    pyproject.toml         # backend project (uv, ruff, mypy, pytest)
    src/loomis/
      cli.py               # `loomis <command>` entry point
      launcher.py          # one-click dev launcher (`loomis up`)
      daemon.py            # background threads: job runner + source watcher
      core/                # shared foundation: config, db + migrations,
                           #   models, repository (SQL), storage, event bus,
                           #   errors, logging, transactions
      ingest/              # sources + the safety spine (feature 01):
                           #   watcher, devicefile, backup
      pipeline/            # job runner + every pipeline step (features 02-05):
                           #   runner, steps, transcode, stt, diarize,
                           #   speakerid, classify, summarize, llm
      cloud/               # opt-in rclone push (feature 06): rclone, sync
      api/                 # HTTP surface (11): app factory, routes, schemas
    tests/
  web/                     # Vue 3 + Vuetify SPA (Vite)
    package.json
    src/                   # pages, components, API client, stores (Pinia)
    index.html
  docs/                    # this documentation
  README.md  LICENSE  ...
```


The backend is the only writer to SQLite + the file library; the frontend is a
pure client. Tooling lives per side: `backend/pyproject.toml`
([ADR-0010](adr/0010-python-tooling.md)) and `web/package.json`
([ADR-0003](adr/0003-frontend-vue-spa.md)).
