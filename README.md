# Loomis

> Local-first voice lifelogger — automatically back up recordings from a USB
> recorder or a watched folder (phone sync, lifelogger export), transcribe
> them, identify who spoke, and turn them into a personal diary and meeting
> notes.

Loomis watches your recording **sources**. Plug in a recorder over USB — or let
your phone's sync tool drop files into a watched folder — and it copies new
recordings to your computer, transcribes them with speaker labels (suggesting
real names from the conversation itself), and uses a local LLM to write them
up: scattered everyday clips become a daily **personal diary** (lifelog), while
clear multi-person discussions become standalone **meeting records** that your
diary links to.

Everything runs **locally by default** — local files, a local SQLite database,
on-device speech-to-text, and [Ollama](https://ollama.com) for the LLM. Cloud
services (OneDrive, Google Drive, …) and cloud LLMs are strictly opt-in.

---

## Status

🚧 **Beta — M1–M4 implemented.** The design is the spec (see [`docs/`](docs/)).
Built so far: the SHA-256 "safety spine" backup from USB recorders **and
watched folders**, the durable processing pipeline (WhisperX transcription,
pyannote diarization, cross-recording speaker identity with LLM name
suggestions, diary/meeting summaries via Ollama), and the Vue + Vuetify web UI
(timeline, transcripts with audio, speakers, search, jobs). Next is **M5 —
Release 1.0**: opt-in cloud sync, packaging, first-run polish
([roadmap](docs/08-roadmap-and-milestones.md)).

## Getting started

Three steps: **install**, set up the **diarization model**, then **run**.

### 1. Install

From the repo root, run the installer for your OS:

```powershell
./install.ps1          # Windows (PowerShell)
```
```bash
./install.sh           # macOS / Linux
```

It installs the full baseline — [uv](https://github.com/astral-sh/uv), Node + pnpm,
**ffmpeg**, **[Ollama](https://ollama.com)** (and pulls the default model), the
backend STT / diarization / LLM extras, and the web dependencies. Add
`-SkipLlmModel` / `--skip-llm-model` to skip the large model download.

> **GPU (NVIDIA):** the installer defaults to the **CUDA** build of PyTorch — the
> `gpu` extra pins torch to the CUDA (cu128) wheels in the lockfile, so the build is
> recorded once and every later `uv run` keeps it (no env var, no new shell needed).
> STT/diarize use `device = "auto"`, so they pick up the GPU automatically. On a
> machine without an NVIDIA GPU, install with `-Cpu` / `--cpu` for the smaller
> CPU-only wheels, and set `[stt].model = "small"` (or `medium`) for usable speed.

> Installing by hand instead: `cd backend && uv sync --extra stt --extra diarize
> --extra llm --extra gpu` (use `--extra cpu` for the CPU-only build), then
> `cd ../web && pnpm install`, with ffmpeg + Ollama on your PATH.

### 2. Diarization model (one-time)

Speaker diarization uses [pyannote](https://github.com/pyannote/pyannote-audio),
whose models download from HuggingFace with a free token. Do this once:

1. Get a **read** token: <https://huggingface.co/settings/tokens>
2. Open these two pages and click **Agree** to the terms:
   [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   · [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
3. Add the token to `~/.loomis/config.toml`:
   ```toml
   [diarize]
   hf_token = "hf_xxxxxxxx"
   ```
   (or set `LOOMIS_DIARIZE__HF_TOKEN` in the environment.)

Skipping this is fine to start — **transcription, diary, and meetings still work**;
only speaker separation and cross-recording identity wait. Add the token later and
press **Retry all** on the Jobs screen. To drop speakers entirely, set
`[diarize].engine` and `[speaker_id].engine` to `"null"`.

### 3. Run

```bash
cd backend
uv run loomis            # backend + web together, one terminal; Ctrl-C stops both
uv run loomis up --prod  # build the SPA and serve it from the backend (no Vite)
uv run loomis check      # report what's installed/detected
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
