# Loomis backend

Python backend for [Loomis](../README.md): core, processing pipeline, background
daemon, and the **FastAPI** REST/WebSocket API the Vue SPA (`../web/`) consumes.

> Pre-alpha. Implemented: typed config, SQLite + migration runner,
> `GET /api/v1/health`, and **M1 — safe ingest**: the backup core (`loomis backup`)
> plus the transcription pipeline — a durable job runner with a swappable STT engine
> and optional Opus transcode (`loomis worker`). Features land per the
> [roadmap](../docs/08-roadmap-and-milestones.md).

## Develop

First-time setup: run the repo-root installer (`../install.ps1` / `../install.sh`)
to get ffmpeg, Ollama, the STT/diarize/LLM extras, and the web deps in one shot.
`uv sync` below installs only the lean base (null engines).

```bash
uv sync                 # create venv + install base (uses Python 3.12)
uv sync --extra stt --extra diarize --extra llm --extra gpu  # full pipeline, CUDA torch
uv sync --extra stt --extra diarize --extra llm --extra cpu  # same, CPU-only torch
uv run loomis            # one-click dev: backend + Vite frontend, one terminal
uv run loomis up --prod  # build the SPA and serve it from the backend (no Vite)
uv run loomis check      # report prerequisite tools (Node, pnpm, ffmpeg, Ollama)
uv run loomis serve      # run only the API at http://127.0.0.1:8080
uv run loomis backup E:\  # import audio from a recorder volume (safety-spine)
uv run loomis backup --watch  # poll for recorders and import on connect
uv run loomis worker --once   # drain the pipeline queue (transcode -> stt) and exit
uv run loomis worker          # run the durable job runner continuously
uv run loomis version

uv run ruff format . && uv run ruff check .
uv run mypy .
uv run pytest
```

`loomis up` (the default) starts the backend and the Vite dev server together,
streams both logs into one terminal, waits for health, opens a browser, and on
Ctrl-C shuts down only its own children — never external services like Ollama.
The frontend needs deps first: `cd ../web && pnpm install`.

> **Daemon:** `serve` / `up` run the background daemon — the durable job runner and
> the device watcher — inside the API process (one SQLite writer; opt-out via
> `[api].run_daemon`). Plug in a recorder while the server is running and it imports
> and processes automatically. The standalone `loomis worker` / `loomis backup`
> CLIs remain for headless/one-shot use; don't run them against the same `data_dir`
> while the daemon is up (avoid two writers).

Layout follows [docs/04 §12](../docs/04-system-architecture.md#12-repository-layout):
the package lives in `src/loomis/`. Config reference:
[docs/06](../docs/06-configuration.md). API contract:
[docs/11](../docs/11-api-specification.md).
