"""Keep browsing responsive no matter how much background work is queued.

Three pieces:

1. Event-loop lag monitor. A coroutine sleeps 250 ms in a loop and
   measures how late it wakes up. Lag means something CPU-bound is
   hogging the single event loop that also serves page requests.

2. In-flight request counter (fed by middleware in main.py). Interactive
   requests are what the user is waiting on.

3. `background_capacity(configured)` — what the queue worker may run
   right now. It sheds parallelism when the loop is laggy or requests
   are in flight, down to ONE task, so background work slows down
   instead of the UI. `await yield_to_requests()` lets the worker pause
   briefly before starting a task while a request is being served.

Plus a stall watchdog THREAD: if the loop's heartbeat is ever more than
STALL_SECONDS old, it logs the main thread's current stack (the code
that's blocking) once per stall, so a hang is diagnosable from
`docker logs jsp-api` instead of a mystery.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback

log = logging.getLogger("jsp.responsiveness")

_TICK = 0.25
STALL_SECONDS = 5.0

_state = {
    "lag_ms": 0.0,          # most recent loop lag
    "lag_ms_max_60s": 0.0,  # worst lag in the last minute
    "heartbeat": time.monotonic(),
    "inflight": 0,
    "stalls": 0,
    "last_stall": None,     # {"at", "seconds", "stack"}
}
_window: list[tuple[float, float]] = []
_main_thread_id: int | None = None


async def monitor_loop() -> None:
    """Run forever in the API process (started in main.lifespan)."""
    global _main_thread_id
    _main_thread_id = threading.get_ident()
    threading.Thread(target=_watchdog, name="jsp-stall-watchdog", daemon=True).start()
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(_TICK)
        now = time.monotonic()
        lag = max(0.0, (now - t0 - _TICK) * 1000.0)
        _state["lag_ms"] = lag
        _state["heartbeat"] = now
        _window.append((now, lag))
        while _window and now - _window[0][0] > 60:
            _window.pop(0)
        _state["lag_ms_max_60s"] = max((lv for _, lv in _window), default=0.0)
        if lag > 1000:
            log.warning("Event loop lagged %.0f ms", lag)


def _watchdog() -> None:
    stalled = False
    while True:
        time.sleep(1.0)
        age = time.monotonic() - _state["heartbeat"]
        if age > STALL_SECONDS and not stalled:
            stalled = True
            _state["stalls"] += 1
            frame = sys._current_frames().get(_main_thread_id or -1)
            stack = "".join(traceback.format_stack(frame)) if frame else "(no frame)"
            _state["last_stall"] = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "seconds": round(age, 1),
                "stack": stack[-4000:],
            }
            log.error(
                "EVENT LOOP STALLED for %.1fs — the API can't serve requests. "
                "Code currently running on the loop:\n%s", age, stack,
            )
        elif age <= STALL_SECONDS and stalled:
            stalled = False
            log.warning("Event loop recovered")


class InflightCounter:
    """ASGI middleware: counts interactive HTTP requests in flight.
    Long-lived streams (SSE) aren't "waiting" requests — excluded."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or "/stream" in scope.get("path", ""):
            return await self.app(scope, receive, send)
        _state["inflight"] += 1
        try:
            return await self.app(scope, receive, send)
        finally:
            _state["inflight"] -= 1


def background_capacity(configured: int) -> int:
    """How many background tasks may run concurrently right now."""
    configured = max(1, int(configured))
    lag = _state["lag_ms"]
    if lag > 1000:
        return 1
    if lag > 250:
        return max(1, configured // 4)
    if _state["inflight"] > 0:
        return max(1, configured // 2)
    return configured


async def yield_to_requests(max_wait: float = 2.0) -> None:
    """Before starting a background task, give in-flight requests up to
    `max_wait` seconds of the loop to themselves."""
    deadline = time.monotonic() + max_wait
    while _state["inflight"] > 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.05)


def snapshot() -> dict:
    return {
        "event_loop_lag_ms": round(_state["lag_ms"], 1),
        "event_loop_lag_ms_max_60s": round(_state["lag_ms_max_60s"], 1),
        "requests_in_flight": _state["inflight"],
        "stalls_since_start": _state["stalls"],
        "last_stall": _state["last_stall"],
    }
