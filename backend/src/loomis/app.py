"""FastAPI application factory.

Hosts the REST/WebSocket surface the Vue SPA consumes
(see ../../docs/11-api-specification.md). Right now only ``/api/v1/health`` exists
— the walking skeleton that proves config + DB + API + frontend wiring works.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__, db
from .config import Settings, get_settings
from .logging_setup import configure_logging

API_PREFIX = "/api/v1"

# app.py -> loomis -> src -> backend -> repo root -> web/dist
_SPA_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    configure_logging(settings.core.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        data_dir = settings.core.resolved_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(data_dir / "loomis.db")
        app.state.db_version = db.apply_migrations(conn)
        app.state.db = conn
        try:
            yield
        finally:
            conn.close()

    app = FastAPI(title="Loomis", version=__version__, lifespan=lifespan)

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get(f"{API_PREFIX}/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "db_version": getattr(app.state, "db_version", None),
        }

    # Prod: serve the built SPA from the backend (dev uses the Vite server instead).
    # html=True makes unknown paths fall back to index.html for client-side routing.
    if settings.api.serve_spa and _SPA_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_SPA_DIST, html=True), name="spa")

    return app
