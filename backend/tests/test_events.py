"""Event bus pub/sub semantics."""

from __future__ import annotations

from loomis.core.events import EventBus, drain


def test_publish_delivers_to_subscriber() -> None:
    bus = EventBus()
    q = bus.subscribe()
    bus.publish("job.updated", {"job_id": 1, "status": "done"})
    events = drain(q)
    assert len(events) == 1
    assert events[0].type == "job.updated"
    assert events[0].data == {"job_id": 1, "status": "done"}


def test_each_subscriber_gets_its_own_copy() -> None:
    bus = EventBus()
    q1, q2 = bus.subscribe(), bus.subscribe()
    bus.publish("device.connected", {"volume": "E:\\"})
    assert len(drain(q1)) == 1
    assert len(drain(q2)) == 1


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.publish("x", {})
    assert drain(q) == []
    assert bus.subscriber_count() == 0
