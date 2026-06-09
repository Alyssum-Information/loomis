# Loomis

> Local-first voice lifelogger — automatically back up recordings from a USB
> recorder, transcribe them, identify who spoke, and turn them into a personal
> diary and meeting notes.

Loomis watches for your audio recorder. The moment you plug it in over USB, it
copies new recordings to your computer, transcribes them with speaker labels,
and uses a local LLM to write them up: scattered everyday clips become a daily
**personal diary** (lifelog), while clear multi-person discussions become
standalone **meeting records** that your diary links to.

Everything runs **locally by default** — local files, a local SQLite database,
on-device speech-to-text, and [Ollama](https://ollama.com) for the LLM. Cloud
services (OneDrive, Google Drive, …) and cloud LLMs are strictly opt-in.

---

## Status

🚧 **Pre-alpha — early implementation.** The design is the spec (see
[`docs/`](docs/)). Built so far: typed config, SQLite + migration runner, the
FastAPI `health` API, the Vue + Vuetify SPA skeleton, and **M1 — safe ingest**:
the SHA-256 "safety spine" backup (`loomis backup`) plus the durable
transcription pipeline (`loomis worker` — WhisperX with optional Opus transcode).
Speakers, summaries, and the full UI follow per the
[roadmap](docs/08-roadmap-and-milestones.md).

## Getting started

### Prerequisites

- **Python 3.12+** and [uv](https://github.com/astral-sh/uv) — backend.
- **Node 18+** and [pnpm](https://pnpm.io) — frontend.
- Optional, added in later milestones: **ffmpeg** (transcode), a running
  **[Ollama](https://ollama.com)** (local LLM), **rclone** (cloud sync). Run
  `uv run loomis check` to see what's detected.

### Install

```bash
git clone https://github.com/kevin/loomis
cd loomis

# Backend (Python)
cd backend && uv sync          # create venv + install from the lockfile

# Frontend (web)
cd ../web && pnpm install      # one-time: install SPA deps
```

### Run

From `backend/`, the one-click launcher starts the API and the Vite dev server
together, streams both logs, waits for health, and opens a browser:

```bash
cd backend
uv run loomis                  # = `loomis up`; Ctrl-C stops both, leaves Ollama etc. running
uv run loomis up --prod        # build the SPA and serve it from the backend (no Vite)
```

The app opens at <http://localhost:3000> (dev) or <http://127.0.0.1:8080>
(`--prod`). Shutdown tears down only Loomis's own processes.

### Back up a recorder (M1)

Import audio from a mounted recorder volume under the integrity safety spine
(copy → SHA-256 verify → commit → optional source delete). First run registers
the device by writing `<volume>/.loomis/device.json`:

```bash
cd backend
uv run loomis backup E:\               # one-shot import from a volume
uv run loomis backup --watch           # poll for recorders, import on connect
uv run loomis backup E:\ --auto-delete # delete each source only after a verified backup
```

Imported audio lands under `~/.loomis/library/`; the metadata ledger is
`~/.loomis/loomis.db`. Re-running is idempotent — already-imported files are
skipped.

### Configure

Loomis reads `<data_dir>/config.toml` (default `~/.loomis/config.toml`), with
`LOOMIS_<SECTION>__<KEY>` environment overrides. Defaults are **local-first** —
no network egress until you opt in. Start from
[`config.example.toml`](config.example.toml); full reference in
[docs/06-configuration.md](docs/06-configuration.md).

### Develop

```bash
cd backend
uv run ruff format . && uv run ruff check . && uv run mypy .
uv run pytest
```

## Features

- 🔌 **Auto-backup on USB connect** — detects a registered recorder and imports
  new recordings, deduplicated against what you already have.
- 🪪 **Device registration** — drops a small `device.json` onto each recorder so
  Loomis can recognize and manage it later.
- 🗑️ **Optional source cleanup** — delete files from the recorder *after* a
  verified backup, to free space (off by default).
- 🗜️ **Optional high-compression archive** — transcode imported audio to
  [Opus](https://opus-codec.org/) to cut storage by ~10× while staying clear for
  speech.
- 📝 **Transcription with speaker labels** — [WhisperX](https://github.com/m-bain/whisperX)
  for accurate, word-timestamped transcripts; [pyannote](https://github.com/pyannote/pyannote-audio)
  for diarization (who spoke when).
- 🧑‍🤝‍🧑 **Cross-recording speaker identity** — builds a voiceprint database so the
  same person is recognized across different recordings.
- 📔 **Two summary modes** — *diary* (first-person daily lifelog) and *meeting*
  (attendees, decisions, action items), chosen automatically and confirmed by the LLM.
- ☁️ **Optional cloud backup** — push your library to OneDrive and other
  providers via [rclone](https://rclone.org).
- 🖥️ **Local web UI** — browse your timeline, diary, meetings, and speakers in a
  [Vue 3 + Vuetify](https://vuetifyjs.com) app talking to a local API; the
  backup/processing daemon runs in the background.

## How it works (at a glance)

```
USB recorder ─▶ Device Watcher ─▶ Backup/Ingest ─▶ (Opus transcode)
                                         │
                                         ▼
                  Processing pipeline (durable job queue)
        STT (WhisperX) ─▶ Diarization ─▶ Speaker ID ─▶ Classify
                                         │
                       ┌─────────────────┴─────────────────┐
                       ▼                                     ▼
            Diary mode (per day)                    Meeting mode (per discussion)
                       └──────────── links ─────────────────┘
                                         │
                            SQLite + file library + Markdown
                                         │
                   backend/ (FastAPI REST/WS)  ◀──▶  web/ (Vue + Vuetify SPA)
                                         │
                                optional rclone cloud sync
```

See [docs/04-system-architecture.md](docs/04-system-architecture.md) for the full design.

## Documentation

Start at the **[docs index](docs/README.md)**. Docs use stable numbered ids
(`LM-NN`); feature specs live in [`docs/features/`](docs/features/).

| # | Document | What it covers |
|---|----------|----------------|
| 01 | [Vision & Scope](docs/01-vision-and-scope.md) | Problem, goals, non-goals, personas |
| 02 | [User Flows](docs/02-user-flows.md) | The main end-to-end user journeys |
| 03 | [Requirements](docs/03-requirements-specification.md) | Functional & non-functional requirements |
| 04 | [System Architecture](docs/04-system-architecture.md) | Components, data flow, processing pipeline |
| 05 | [Data Model & Storage](docs/05-data-model-and-storage.md) | SQLite schema, device file, on-disk layout |
| 06 | [Configuration](docs/06-configuration.md) | Configuration reference |
| 01–06 | [Feature specs](docs/features/) | Backup, compression, transcription, speakers, summaries, cloud |
| 07 | [UI / UX Design](docs/07-ui-ux-design.md) | Local web UI |
| 08 | [Roadmap](docs/08-roadmap-and-milestones.md) | Milestones |
| 09 | [Security & Privacy](docs/09-security-and-privacy-model.md) | Trust boundary, credentials, voiceprints |
| 10 | [Glossary](docs/10-glossary.md) | Terms |
| 11 | [API Specification](docs/11-api-specification.md) | Backend ↔ frontend REST/WebSocket contract |
| — | [ADRs](docs/adr/README.md) | Why we chose each tool (+ alternatives) |

## Tech stack (planned)

| Concern | Choice | Why |
|---------|--------|-----|
| Backend (`backend/`) | Python 3.12+, [uv](https://github.com/astral-sh/uv), [ruff](https://github.com/astral-sh/ruff), mypy, pytest | Modern, fast, single `pyproject.toml` |
| Frontend (`web/`) | [Vue 3](https://vuejs.org) + [Vuetify](https://vuetifyjs.com), [Vite](https://vite.dev), Pinia | Batteries-included Material UI for a data-dense lifelog |
| API | [FastAPI](https://fastapi.tiangolo.com) REST + WebSocket | pydantic reuse, async, OpenAPI → typed client |
| Speech-to-text | WhisperX (faster-whisper backend) | 99 languages incl. Mandarin, word timestamps |
| Diarization | pyannote 3.1 (via WhisperX) | Flexible speaker count, strong accuracy |
| LLM | Ollama (default), optional cloud | Local-first, private; pluggable |
| Database | SQLite | Zero-setup, local, durable |
| Audio compression | Opus via ffmpeg | Best-in-class speech compression |
| Cloud sync | rclone | 70+ providers behind one integration |

See the [ADRs](docs/adr/) for the reasoning and the alternatives considered.

## License

[MIT](LICENSE)
