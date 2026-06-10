"""Walking-skeleton test: the health endpoint comes up over a temp data dir."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from loomis.api.app import create_app
from loomis.core.config import ApiSettings, CoreSettings, Settings


def _settings(tmp_path: Path) -> Settings:
    # Daemon off: tests must not poll real volumes or spawn background threads.
    return Settings(core=CoreSettings(data_dir=tmp_path), api=ApiSettings(run_daemon=False))


def test_health_ok(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_db_created(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))):
        pass
    assert (tmp_path / "loomis.db").exists()
