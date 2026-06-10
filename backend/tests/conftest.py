"""Shared test fixtures.

``Settings`` is a pydantic ``BaseSettings``: it reads ``LOOMIS_*`` environment
variables and the developer's real ``config.toml``, both of which take
precedence over values passed in test code (06 §1). Without isolation, editing
your own config changes test outcomes — so every test runs with the env
scrubbed and the config file pointed at a nonexistent temp path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("LOOMIS_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("LOOMIS_CONFIG", str(tmp_path / "no-such-config.toml"))
