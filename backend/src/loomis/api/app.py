"""FastAPI application factory.

Hosts the REST/WebSocket surface the Vue SPA consumes
(see ../../../docs/11-api-specification.md): the lifespan opens the DB, applies
migrations, and (unless disabled) starts the in-process background daemon.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..core import db
from ..core.config import Settings, get_settings
from ..core.events import EventBus
from ..core.logging_setup import configure_logging
from ..daemon import Daemon
from .routes import install_error_handlers
from .routes import router as api_router

API_PREFIX = "/api/v1"

# app.py -> api -> loomis -> src -> backend -> repo root -> web/dist
_SPA_DIST = Path(__file__).resolve().parents[4] / "web" / "dist"


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    configure_logging(settings.core.log_level)

    # LAN exposure requires a token (11 §2): refuse a non-loopback bind without
    # one rather than silently serving the lifelog to the network.
    if settings.api.host not in _LOOPBACK_HOSTS and not settings.api.token:
        raise RuntimeError(
            f"[api].host = {settings.api.host!r} exposes Loomis beyond this machine; "
            "set LOOMIS_API__TOKEN (or bind to 127.0.0.1)"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        data_dir = settings.core.resolved_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(data_dir / "loomis.db")
        app.state.db_version = db.apply_migrations(conn)
        app.state.db = conn

        # Event bus is always present (WS subscribes to it); the daemon that feeds
        # it is opt-out via [api].run_daemon (off in tests).
        app.state.bus = EventBus()
        daemon = Daemon(settings, app.state.bus) if settings.api.run_daemon else None
        if daemon is not None:
            daemon.start()
        app.state.daemon = daemon
        try:
            yield
        finally:
            if daemon is not None:
                daemon.stop()
            conn.close()

    app = FastAPI(title="Loomis", version=__version__, lifespan=lifespan)
    # Available to request handlers (the per-request DB dependency reads it).
    app.state.settings = settings

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    if settings.api.token:
        # Bearer auth on the whole API surface once a token is configured (11 §2).
        expected = f"Bearer {settings.api.token}"

        @app.middleware("http")
        async def require_token(request: Request, call_next: Any) -> Any:
            if request.url.path.startswith(API_PREFIX) and not secrets.compare_digest(
                request.headers.get("authorization", ""), expected
            ):
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": 401, "message": "missing or invalid API token"}},
                )
            return await call_next(request)

    @app.get(f"{API_PREFIX}/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "db_version": getattr(app.state, "db_version", None),
        }

    install_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)

    # Prod: serve the built SPA from the backend (dev uses the Vite server instead).
    # html=True makes unknown paths fall back to index.html for client-side routing.
    # Mounted last so it only catches paths the API router didn't.
    if settings.api.serve_spa and _SPA_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_SPA_DIST, html=True), name="spa")

    return app
