# Loomis backend

Python backend for [Loomis](../README.md): core, processing pipeline, background
daemon, and the **FastAPI** REST/WebSocket API the Vue SPA (`../web/`) consumes.

> Pre-alpha. Currently a **walking skeleton**: typed config, SQLite + migration
> runner, and `GET /api/v1/health`. Features land per the
> [roadmap](../docs/08-roadmap-and-milestones.md).

## Develop

```bash
uv sync                 # create venv + install (uses Python 3.12)
uv run loomis serve     # run the API at http://127.0.0.1:8080
uv run loomis version

uv run ruff format . && uv run ruff check .
uv run mypy .
uv run pytest
```

Layout follows [docs/04 §12](../docs/04-system-architecture.md#12-repository-layout):
the package lives in `src/loomis/`. Config reference:
[docs/06](../docs/06-configuration.md). API contract:
[docs/11](../docs/11-api-specification.md).
