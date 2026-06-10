"""Removable-volume detection (FR-1.1).

Baseline cross-platform adapter: poll mounted removable volumes via **psutil**
every ``poll_interval_s`` and diff the set into connect/remove events. Native
event sources (Windows WMI, Linux pyudev) are an optional optimisation deferred
to later — see [ADR-0011](../../docs/adr/0011-usb-device-detection.md).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import psutil


def removable_volumes() -> set[Path]:
    """Currently-mounted removable volumes (mountpoints).

    psutil flags removable media with ``removable`` (Windows) / ``hotplug`` in the
    partition ``opts``. Volumes that vanished mid-scan are skipped.
    """
    found: set[Path] = set()
    for part in psutil.disk_partitions(all=False):
        opts = part.opts.lower()
        if "removable" in opts or "hotplug" in opts:
            mount = Path(part.mountpoint)
            if mount.exists():
                found.add(mount)
    return found


class DeviceWatcher:
    """Polls :func:`removable_volumes` and fires callbacks on set changes."""

    def __init__(self, poll_interval_s: float = 3.0) -> None:
        self.poll_interval_s = poll_interval_s
        self._known: set[Path] = set()

    def poll_once(self) -> tuple[set[Path], set[Path]]:
        """Return ``(added, removed)`` since the previous poll and update state."""
        current = removable_volumes()
        added = current - self._known
        removed = self._known - current
        self._known = current
        return added, removed

    def watch(
        self,
        on_connect: Callable[[Path], None],
        on_remove: Callable[[Path], None] | None = None,
        *,
        stop: threading.Event | None = None,
    ) -> None:
        """Block polling until ``stop`` is set, dispatching connect/remove events.

        The initial poll treats already-mounted volumes as fresh connects so a
        device plugged in before startup is still imported.
        """
        stop = stop or threading.Event()
        while not stop.is_set():
            added, removed = self.poll_once()
            for vol in sorted(added):
                on_connect(vol)
            if on_remove is not None:
                for vol in sorted(removed):
                    on_remove(vol)
            stop.wait(self.poll_interval_s)
