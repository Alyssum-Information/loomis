"""Process-wide logging configuration.

Without this, the warnings/errors the backup engine emits (copy failures, hash
mismatches, low disk space) go to a handler-less root logger and vanish. Entry
points call :func:`configure_logging` once, honouring ``[core].log_level``.
"""

from __future__ import annotations

import logging

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Install a single stderr handler at ``level`` (idempotent)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    _configured = True
