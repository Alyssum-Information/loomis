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

🚧 **Pre-alpha — planning stage.** This repository currently contains the
project design and documentation only; application code has not been written
yet. See [`docs/`](docs/) for the full plan and the
[roadmap](docs/08-roadmap-and-milestones.md).

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
