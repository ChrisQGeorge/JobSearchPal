"""In-memory pub/sub for live-streaming queue-worker activity to the UI.

Not persistent — each event is broadcast to every currently-subscribed SSE
consumer and then forgotten. Single-process / single-container by design.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

# Every active subscriber owns an asyncio.Queue. Publishing a dict to the
# bus copies it into every subscriber's queue. If a queue is full (backed-up
# slow consumer) we drop, rather than block the worker.
_SUBSCRIBERS: set[asyncio.Queue] = set()
_MAX_BUFFER = 500


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_BUFFER)
    _SUBSCRIBERS.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _SUBSCRIBERS.discard(q)


def publish(event: dict[str, Any]) -> None:
    """Fan-out to every subscriber. Never blocks; drops for slow consumers."""
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Slow consumer — drop this event for them.
            log.debug("queue_bus subscriber full; dropping event")


def has_subscribers() -> bool:
    return bool(_SUBSCRIBERS)
