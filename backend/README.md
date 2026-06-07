# Loomis backend

Python backend for [Loomis](../README.md): core, processing pipeline, background
daemon, and the **FastAPI** REST/WebSocket API the Vue SPA (`../web/`) consumes.

> Pre-alpha. Implemented: typed config, SQLite + migration runner,
> `GET /api/v1/health`, and the **M1 backup core** — device registration and the
> SHA-256 safety-spine import (`loomis backup`). Features land per the
> [roadmap](../docs/08-roadmap-and-milestones.md).

## Develop

```bash
uv sync                 # create venv + install (uses Python 3.12)
uv run loomis            # one-click dev: backend + Vite frontend, one terminal
uv run loomis up --prod  # build the SPA and serve it from the backend (no Vite)
uv run loomis check      # report prerequisite tools (Node, pnpm, ffmpeg, Ollama)
uv run loomis serve      # run only the API at http://127.0.0.1:8080
uv run loomis backup E:\  # import audio from a recorder volume (safety-spine)
uv run loomis backup --watch  # poll for recorders and import on connect
uv run loomis version

uv run ruff format . && uv run ruff check .
uv run mypy .
uv run pytest
```

`loomis up` (the default) starts the backend and the Vite dev server together,
streams both logs into one terminal, waits for health, opens a browser, and on
Ctrl-C shuts down only its own children — never external services like Ollama.
The frontend needs deps first: `cd ../web && pnpm install`.

> **M1 note:** `loomis backup` runs as its own process and writes the database
> directly. Until the background daemon arrives, don't run a backup and the API
> server against the same `data_dir` at the same time (single-writer assumption).
> Device auto-import is via `loomis backup --watch`; `serve`/`up` do not yet watch.

Layout follows [docs/04 §12](../docs/04-system-architecture.md#12-repository-layout):
the package lives in `src/loomis/`. Config reference:
[docs/06](../docs/06-configuration.md). API contract:
[docs/11](../docs/11-api-specification.md).
