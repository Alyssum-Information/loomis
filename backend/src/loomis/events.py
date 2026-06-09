"""In-process event bus for live backend → UI updates (04 §3.2, 11 §4).

The daemon's background workers (job runner, device watcher) and the pipeline
publish small events here; the WebSocket endpoint (added later) subscribes and
relays them to the SPA, so the UI reflects backend state without polling. Pure
stdlib, thread-safe; no external broker.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Any

log = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 1000  # per-subscriber backlog cap; a stalled consumer drops events, never blocks


@dataclass(frozen=True, slots=True)
class Event:
    type: str  # e.g. "job.updated", "device.connected" (see 11 §4)
    data: dict[str, Any]


class EventBus:
    """Fan-out pub/sub over thread-safe queues. One queue per subscriber."""

    def __init__(self) -> None:
        self._subscribers: set[Queue[Event]] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> Queue[Event]:
        """Register a new subscriber and return its event queue."""
        q: Queue[Event] = Queue(maxsize=_QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: Queue[Event]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, type: str, data: dict[str, Any]) -> None:  # noqa: A002 (event "type" field)
        """Deliver an event to every subscriber. A full queue drops it (never blocks)."""
        event = Event(type=type, data=data)
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(event)
            except Full:
                log.warning("event subscriber backlog full; dropping %s", type)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


def drain(q: Queue[Event]) -> list[Event]:
    """Non-blocking: pull all currently-queued events (handy for tests)."""
    out: list[Event] = []
    while True:
        try:
            out.append(q.get_nowait())
        except Empty:
            return out
