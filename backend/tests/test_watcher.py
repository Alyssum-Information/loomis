"""Device-watcher diff logic (mocked volume set — no real hardware needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from loomis import watcher
from loomis.watcher import DeviceWatcher


def test_removable_volumes_returns_paths() -> None:
    # Smoke: never raises; result is a set of Paths (usually empty in CI).
    vols = watcher.removable_volumes()
    assert isinstance(vols, set)
    assert all(isinstance(v, Path) for v in vols)


def test_poll_once_reports_added_then_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"vols": {Path("E:/")}}
    monkeypatch.setattr(watcher, "removable_volumes", lambda: set(state["vols"]))

    w = DeviceWatcher(poll_interval_s=0.01)
    added, removed = w.poll_once()
    assert added == {Path("E:/")}
    assert removed == set()

    # No change → no events.
    added, removed = w.poll_once()
    assert added == set() and removed == set()

    # Unplug → reported as removed once.
    state["vols"] = set()
    added, removed = w.poll_once()
    assert added == set()
    assert removed == {Path("E:/")}
