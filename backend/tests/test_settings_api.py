"""Settings API + egress surfacing (FR-7.7, FR-7.8) and the LAN token guard (11 §2)."""

from __future__ import annotations

import sqlite3
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loomis.api.app import create_app
from loomis.core import db
from loomis.core.config import (
    ApiSettings,
    BackupSettings,
    CoreSettings,
    DiarizeSettings,
    Settings,
)
from loomis.core.events import EventBus, drain
from loomis.core.models import TranscodePolicy


def _settings(tmp_path: Path, **api_overrides: object) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        backup=BackupSettings(
            folder_settle_seconds=0.0, transcode_policy=TranscodePolicy.KEEP_ORIGINAL
        ),
        api=ApiSettings(run_daemon=False, serve_spa=False, **api_overrides),  # type: ignore[arg-type]
        diarize=DiarizeSettings(engine="null", hf_token="hf_secret"),  # noqa: S106 (fake)
    )


def _prepare_db(settings: Settings) -> None:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection = db.connect(data_dir / "loomis.db")
    db.apply_migrations(conn)
    conn.close()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = _settings(tmp_path)
    _prepare_db(settings)
    with TestClient(create_app(settings)) as c:
        yield c


def test_get_settings_curates_secrets(client: TestClient) -> None:
    body = client.get("/api/v1/settings").json()
    assert "token" not in body["settings"]["api"]
    assert body["settings"]["diarize"]["hf_token"] == "********"  # noqa: S105 (the mask)
    assert body["egress"] == {"cloud_sync": False, "cloud_llm": False, "lan_bind": False}
    assert body["config_path"].endswith("config.toml")


def test_patch_applies_live_and_persists(client: TestClient, tmp_path: Path) -> None:
    resp = client.patch("/api/v1/settings", json={"stt": {"language": "zh"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == ["stt.language"]
    assert body["restart_required"] is False
    assert body["egress_pending"] == []

    # Applied live (no restart) …
    envelope = client.get("/api/v1/settings").json()
    assert envelope["settings"]["stt"]["language"] == "zh"
    # … and persisted to the config file the API reports (conftest points it at tmp).
    config = tomllib.loads(Path(envelope["config_path"]).read_text(encoding="utf-8"))
    assert config["stt"]["language"] == "zh"


def test_patch_rejects_unknown_blocked_and_invalid(client: TestClient) -> None:
    assert client.patch("/api/v1/settings", json={"nope": {"x": 1}}).status_code == 422
    assert client.patch("/api/v1/settings", json={"stt": {"nope": 1}}).status_code == 422
    assert client.patch("/api/v1/settings", json={"api": {"token": "x"}}).status_code == 422
    resp = client.patch("/api/v1/settings", json={"jobs": {"max_attempts": "many"}})
    assert resp.status_code == 422
    assert "max_attempts" in resp.json()["error"]["message"]


def test_masked_secret_echo_is_a_noop(client: TestClient, tmp_path: Path) -> None:
    # A UI that saves the whole form echoes the mask back; that must not overwrite.
    resp = client.patch(
        "/api/v1/settings", json={"diarize": {"hf_token": "********", "device": "cpu"}}
    )
    assert resp.json()["applied"] == ["diarize.device"]
    config_path = Path(client.get("/api/v1/settings").json()["config_path"])
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "hf_token" not in config.get("diarize", {})


def test_enabling_cloud_flags_egress_and_publishes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _prepare_db(settings)
    with TestClient(create_app(settings)) as client:
        bus: EventBus = client.app.state.bus  # type: ignore[attr-defined]
        q = bus.subscribe()
        resp = client.patch("/api/v1/settings", json={"cloud": {"enabled": True}})
        body = resp.json()
        assert body["egress_pending"] == ["cloud_sync"]
        assert body["egress"]["cloud_sync"] is True
        events = drain(q)
        assert [e.type for e in events] == ["egress.pending"]
        assert events[0].data["kind"] == "cloud_sync"

        # Already enabled → not "pending" again on an unrelated change.
        resp = client.patch("/api/v1/settings", json={"cloud": {"schedule_cron": "0 3 * * *"}})
        assert resp.json()["egress_pending"] == []


def test_restart_required_flagged(client: TestClient) -> None:
    resp = client.patch("/api/v1/settings", json={"api": {"port": 9090}})
    assert resp.json()["restart_required"] is True


# --- LAN bind guard + bearer token (11 §2) ---


def test_lan_bind_without_token_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path, host="0.0.0.0")  # noqa: S104 (the rejected case)
    with pytest.raises(RuntimeError, match="LOOMIS_API__TOKEN"):
        create_app(settings)


def test_token_enforced_when_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path, token="s3cret")  # noqa: S106 (test credential)
    _prepare_db(settings)
    with TestClient(create_app(settings)) as client:
        unauth = client.get("/api/v1/settings")
        assert unauth.status_code == 401
        assert unauth.json()["error"]["code"] == 401

        ok = client.get("/api/v1/settings", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200
        assert (
            client.get("/api/v1/health", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )


def test_websocket_requires_token_when_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path, token="s3cret")  # noqa: S106 (test credential)
    _prepare_db(settings)
    with TestClient(create_app(settings)) as client:
        import contextlib

        # Wrong/missing token → server closes before accepting traffic.
        with contextlib.suppress(Exception), client.websocket_connect("/api/v1/ws") as ws:
            assert ws.receive() == {
                "type": "websocket.close",
                "code": 4401,
                "reason": "missing or invalid API token",
            }

        # Query-param token works (browsers cannot set WS headers).
        with client.websocket_connect("/api/v1/ws?token=s3cret"):
            pass
