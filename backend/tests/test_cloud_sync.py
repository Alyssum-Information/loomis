"""Cloud sync (FR-8.1 … FR-8.4): push-only rclone wrapper, job handler, API."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loomis.api.app import create_app
from loomis.cloud.rclone import Rclone
from loomis.cloud.sync import handle_cloud_sync, sync_remote
from loomis.core import db, repository
from loomis.core.config import (
    ApiSettings,
    BackupSettings,
    CloudRemote,
    CloudSettings,
    CoreSettings,
    Settings,
)
from loomis.core.errors import PermanentJobError
from loomis.core.models import JobType, TranscodePolicy
from loomis.pipeline.runner import JobRunner
from loomis.pipeline.steps import JobContext


class FakeRclone:
    """Records pushes instead of shelling out."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls: list[tuple[Path, str]] = []
        _FAKE_INSTANCES.append(self)

    def available(self) -> bool:
        return True

    def copy(self, src: Path, dest: str) -> str:
        self.calls.append((src, dest))
        return "1 B / 1 B, 100%, 0 B/s"


_FAKE_INSTANCES: list[FakeRclone] = []


def _all_calls() -> list[tuple[Path, str]]:
    return [c for inst in _FAKE_INSTANCES for c in inst.calls]


@pytest.fixture(autouse=True)
def _reset_fakes() -> Iterator[None]:
    _FAKE_INSTANCES.clear()
    yield


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(
        core=CoreSettings(data_dir=tmp_path / "data"),
        backup=BackupSettings(
            folder_settle_seconds=0.0, transcode_policy=TranscodePolicy.KEEP_ORIGINAL
        ),
        api=ApiSettings(run_daemon=False, serve_spa=False),
        cloud=CloudSettings(
            enabled=enabled,
            remotes=[
                CloudRemote(name="onedrive", scope=["audio", "markdown", "db"], dest="loomis"),
                CloudRemote(name="gdrive", scope=["markdown"]),
            ],
        ),
    )


def _conn(settings: Settings) -> sqlite3.Connection:
    data_dir = settings.core.resolved_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    c = db.connect(data_dir / "loomis.db")
    db.apply_migrations(c)
    return c


def _seed_files(settings: Settings) -> Path:
    data_dir = settings.core.resolved_data_dir
    (data_dir / "library" / "rec").mkdir(parents=True, exist_ok=True)
    (data_dir / "library" / "rec" / "a.opus").write_bytes(b"opus")
    (data_dir / "diary").mkdir(parents=True, exist_ok=True)
    (data_dir / "diary" / "2026-06-09.md").write_text("# day", encoding="utf-8")
    # no meetings/ dir on purpose: missing scope dirs are skipped, not an error
    return data_dir


def test_copy_args_are_push_only() -> None:
    args = Rclone("rclone").copy_args(Path("x"), "remote:loomis/library")
    assert args[1] == "copy"  # copy never deletes anything (FR-8.4)
    assert "sync" not in args
    assert "--delete-before" not in " ".join(args)


def test_sync_remote_pushes_scopes_and_logs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    data_dir = _seed_files(settings)
    fake = FakeRclone()

    sync_remote(conn, settings, settings.cloud.remotes[0], rclone=fake)  # type: ignore[arg-type]

    dests = [d for _, d in fake.calls]
    assert "onedrive:loomis/library" in dests
    assert "onedrive:loomis/diary" in dests
    assert "onedrive:loomis/db" in dests
    assert all(d.startswith("onedrive:") for d in dests)
    # meetings/ does not exist yet → skipped silently
    assert "onedrive:loomis/meetings" not in dests

    # db scope pushed a consistent snapshot, which is itself a valid sqlite db
    snapshot = data_dir / "cache" / "db-backup" / "loomis.db"
    assert snapshot.is_file()
    check = sqlite3.connect(snapshot)
    assert check.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 9
    check.close()

    entries = repository.list_cloud_sync_log(conn)
    assert len(entries) == 1
    assert entries[0].remote == "onedrive"
    assert entries[0].result == "ok"
    assert entries[0].finished_at is not None


def test_sync_remote_failure_logs_error_and_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_files(settings)

    class BoomRclone(FakeRclone):
        def copy(self, src: Path, dest: str) -> str:
            raise RuntimeError("network down")

    with pytest.raises(RuntimeError, match="network down"):
        sync_remote(conn, settings, settings.cloud.remotes[0], rclone=BoomRclone())  # type: ignore[arg-type]

    entries = repository.list_cloud_sync_log(conn)
    assert entries[0].result == "error"
    assert "network down" in str(entries[0].stats.get("error"))


def test_handler_refuses_when_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, enabled=False)
    conn = _conn(settings)
    job_id = repository.enqueue_job(conn, JobType.CLOUD_SYNC, {})
    job = repository.claim_job(conn, "w", lease_seconds=60, types=(JobType.CLOUD_SYNC,))
    assert job is not None and job.id == job_id

    with pytest.raises(PermanentJobError, match="disabled"):
        handle_cloud_sync(JobContext(conn, settings), job)


def test_cloud_sync_job_runs_via_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("loomis.cloud.sync.Rclone", FakeRclone)
    settings = _settings(tmp_path)
    conn = _conn(settings)
    _seed_files(settings)
    repository.enqueue_job(conn, JobType.CLOUD_SYNC, {"remote": "gdrive"})

    assert JobRunner(settings).drain(conn) == 1

    dests = [d for _, d in _all_calls()]
    assert dests == ["gdrive:loomis/diary"]  # only the named remote, only its scope
    entries = repository.list_cloud_sync_log(conn)
    assert [e.remote for e in entries] == ["gdrive"]
    assert conn.execute("SELECT status FROM jobs").fetchone()["status"] == "done"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = _settings(tmp_path)
    _conn(settings).close()
    with TestClient(create_app(settings)) as c:
        yield c


def test_cloud_api_endpoints(client: TestClient, tmp_path: Path) -> None:
    status = client.get("/api/v1/cloud/remotes").json()
    assert status["enabled"] is True
    assert [r["name"] for r in status["remotes"]] == ["onedrive", "gdrive"]
    assert all(r["direction"] == "push" for r in status["remotes"])

    assert client.post("/api/v1/cloud/sync", json={"remote": "nope"}).status_code == 404

    resp = client.post("/api/v1/cloud/sync", json={})
    assert resp.status_code == 202
    assert resp.json()["job_id"] > 0

    assert client.get("/api/v1/cloud/log").json() == []  # job not executed (daemon off)


def test_cloud_sync_api_refused_when_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, enabled=False)
    _conn(settings).close()
    with TestClient(create_app(settings)) as client:
        resp = client.post("/api/v1/cloud/sync", json={})
        assert resp.status_code == 409
        assert client.get("/api/v1/cloud/remotes").json()["enabled"] is False
