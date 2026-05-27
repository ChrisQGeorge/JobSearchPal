"""In-memory pub/sub for live-streaming queue-worker activity to the UI.

Not persistent — each event is broadcast to every currently-subscribed SSE
consumer and then forgotten. Single-process / single-container by design.

Also maintains a derived *task registry*: one row per (source, item_id) with
rolled-up status, progress snippet, cost, etc. This is what the Companion
Activity page's "tasks" section reads from — so every skill that publishes
to the bus automatically gets a task row without each caller having to
write its own persistence.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Every active subscriber owns an asyncio.Queue. Publishing a dict to the
# bus copies it into every subscriber's queue. If a queue is full (backed-up
# slow consumer) we drop, rather than block the worker.
_SUBSCRIBERS: set[asyncio.Queue] = set()
_MAX_BUFFER = 500


# ---------------------------------------------------------------------------
# Task registry — derived from events. Keyed by f"{source}:{item_id}".
# ---------------------------------------------------------------------------
# Each entry:
#   {
#     "key": str,              # stable composite id, "source:item_id"
#     "source": str,
#     "item_id": str,
#     "label": str,
#     "status": "running" | "done" | "error",
#     "started_at": iso str,
#     "updated_at": iso str,
#     "finished_at": iso str | null,
#     "last_text": str | null,   # most recent non-empty assistant text snippet
#     "last_tool": str | null,   # name of the most recent tool invocation
#     "cost_usd": float | null,
#     "duration_ms": int | null,
#     "num_turns": int | null,
#     "error": str | null,
#     "event_count": int,
#   }
_TASKS: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
# Room for ~a day of heavy use without growing unbounded. LRU-evicted.
_TASKS_CAP = 200
# Separate subscriber set for task-registry change notifications (lighter-
# weight than the raw-event stream — one row update per message).
_TASK_SUBSCRIBERS: set[asyncio.Queue] = set()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _trim_text(text: str, cap: int = 240) -> str:
    text = text.strip()
    if len(text) <= cap:
        return text
    return text[: cap - 1] + "…"


def _task_key(source: str, item_id: Any) -> str:
    return f"{source}:{item_id}"


def _fan_task_update(task: dict[str, Any]) -> None:
    payload = {"kind": "task_update", **task}
    for q in list(_TASK_SUBSCRIBERS):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            log.debug("task subscriber full; dropping update")


def _apply_event_to_registry(event: dict[str, Any]) -> None:
    """Roll a bus event into the task registry row. No-op for events
    that don't identify a task (no source or no item_id)."""
    source = event.get("source")
    item_id = event.get("item_id")
    if not source or item_id is None:
        return
    key = _task_key(source, item_id)
    now = _now_iso()
    task = _TASKS.get(key)
    if task is None:
        task = {
            "key": key,
            "source": source,
            "item_id": str(item_id),
            "label": event.get("label") or source,
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "last_text": None,
            "last_tool": None,
            "cost_usd": None,
            "duration_ms": None,
            "num_turns": None,
            "error": None,
            "event_count": 0,
        }
        _TASKS[key] = task
        # LRU-evict the oldest when over cap.
        while len(_TASKS) > _TASKS_CAP:
            _TASKS.popitem(last=False)
    else:
        # Move to end of the OrderedDict (most-recent-first ordering).
        _TASKS.move_to_end(key, last=True)

    task["updated_at"] = now
    task["event_count"] += 1
    if event.get("label"):
        task["label"] = event["label"]

    kind = event.get("kind")
    if kind == "start":
        task["status"] = "running"
        task["started_at"] = task.get("started_at") or now
    elif kind == "text":
        txt = (event.get("text") or "").strip()
        if txt:
            task["last_text"] = _trim_text(txt)
    elif kind == "tool_use":
        tool = event.get("tool")
        if tool:
            task["last_tool"] = tool
    elif kind == "result":
        task["status"] = "done"
        task["finished_at"] = now
        task["cost_usd"] = event.get("cost_usd")
        task["duration_ms"] = event.get("duration_ms")
        task["num_turns"] = event.get("num_turns")
    elif kind == "done":
        # Several emitters (companion chat stream, fetch handler) publish a
        # terminal `done` event. Treat it as functionally equivalent to
        # `result` — without this, those tasks sit in "running" state
        # forever in the registry. cost/duration/num_turns may already
        # have been set by a preceding `result` event; don't overwrite.
        task["status"] = "done"
        task["finished_at"] = now
        if event.get("cost_usd") is not None:
            task["cost_usd"] = event.get("cost_usd")
        if event.get("duration_ms") is not None:
            task["duration_ms"] = event.get("duration_ms")
        if event.get("num_turns") is not None:
            task["num_turns"] = event.get("num_turns")
    elif kind == "error":
        task["status"] = "error"
        task["finished_at"] = now
        task["error"] = _trim_text(str(event.get("text") or "unknown error"), cap=500)

    _fan_task_update(task)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_BUFFER)
    _SUBSCRIBERS.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _SUBSCRIBERS.discard(q)


def subscribe_tasks() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_BUFFER)
    _TASK_SUBSCRIBERS.add(q)
    return q


def unsubscribe_tasks(q: asyncio.Queue) -> None:
    _TASK_SUBSCRIBERS.discard(q)


# How long a task can sit in `running` with no event before we lazily
# mark it `stale`. Catches any case where the terminal `done`/`result`/
# `error` event got lost (uvicorn killed the request mid-stream, client
# disconnect, producer crash before final emit, etc.). 20 min is well
# past stream_claude_prompt's 15 min internal timeout, so a genuinely
# running long task still gets to finish without being prematurely flagged.
_TASK_STALE_AFTER_SECONDS = 20 * 60


def _maybe_mark_stale(task: dict[str, Any]) -> None:
    """If `task` is `running` and hasn't been updated in
    _TASK_STALE_AFTER_SECONDS, transition it to status=stale in-place.
    Pure local helper — caller decides when to invoke."""
    if task.get("status") != "running":
        return
    updated = task.get("updated_at")
    if not updated:
        return
    try:
        ts = datetime.fromisoformat(updated)
    except ValueError:
        return
    now = datetime.now(tz=timezone.utc)
    if (now - ts).total_seconds() < _TASK_STALE_AFTER_SECONDS:
        return
    task["status"] = "stale"
    task["finished_at"] = _now_iso()
    task["error"] = (
        f"No terminal event after {_TASK_STALE_AFTER_SECONDS // 60} min "
        "— marked stale by lazy sweep. The Claude subprocess may have "
        "been killed mid-stream or the SSE connection dropped."
    )


def list_tasks(limit: int = 100) -> list[dict[str, Any]]:
    """Snapshot of the task registry, most recent first. Lazy-stale any
    long-running entries on each read."""
    rows = list(_TASKS.values())
    rows.reverse()  # most-recent first
    for r in rows[:limit]:
        _maybe_mark_stale(r)
    return rows[:limit]


def get_task(source: str, item_id: Any) -> dict[str, Any] | None:
    """Point-lookup of a single task registry entry, or None if absent.
    Callers supply the same (source, item_id) they'd pass to publish()."""
    task = _TASKS.get(_task_key(source, item_id))
    if task is not None:
        _maybe_mark_stale(task)
    return task


def cancel_task(key: str) -> dict[str, Any] | None:
    """User-initiated termination of a registry entry. Flips status to
    "cancelled" with a clear error message and fans the update to
    subscribers. Returns the updated task, or None if no such key
    exists.

    Note: this does NOT actually stop a running Claude subprocess —
    those are tied to their request scope, not globally tracked. This
    is purely a registry cleanup: removes the stuck row from the
    Companion Activity feed so the user can move on. If a real
    subprocess is still alive, it'll finish (or hit its own timeout)
    on its own; any events it emits after this point will re-create
    the row, which is fine — the user can cancel again."""
    task = _TASKS.get(key)
    if task is None:
        return None
    task["status"] = "cancelled"
    task["finished_at"] = _now_iso()
    task["updated_at"] = task["finished_at"]
    task["error"] = "Cancelled from the Companion Activity page."
    _fan_task_update(task)
    return task


def publish(event: dict[str, Any]) -> None:
    """Fan-out to every subscriber + update the task registry.
    Never blocks; drops for slow consumers."""
    # Keep registry updated even if nobody is subscribed (lets users navigate
    # to /queue after the fact and still see rows).
    try:
        _apply_event_to_registry(event)
    except Exception:
        log.exception("queue_bus: failed to apply event to task registry")
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Slow consumer — drop this event for them.
            log.debug("queue_bus subscriber full; dropping event")


def has_subscribers() -> bool:
    return bool(_SUBSCRIBERS) or bool(_TASK_SUBSCRIBERS)


async def run_claude_to_bus(
    *,
    prompt: str,
    source: str,
    item_id: str | int,
    label: str,
    allowed_tools: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: int = 240,
    action: str | None = None,
) -> str:
    """Run Claude Code via the streaming variant and fan events onto the bus.

    Shared by fetch / jd-analyze / humanize / whatever else wants its
    output narrated live. `source` labels the activity for UI grouping;
    `item_id` is a stable key per logical unit of work (`"jd:42"`,
    `"fetch-queue:9"`, etc.). Returns the assistant's concatenated text
    so the caller can parse the final JSON.
    """
    from datetime import datetime as _dt, timezone as _tz

    from app.skills.runner import ClaudeCodeError, stream_claude_prompt

    def emit(ev: dict) -> None:
        payload = {
            **ev,
            "source": source,
            "item_id": item_id,
            "label": label,
            "t": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
        }
        publish(payload)

    emit({"kind": "start"})
    collected: list[str] = []
    had_error: str | None = None
    try:
        async for raw in stream_claude_prompt(
            prompt=prompt,
            allowed_tools=allowed_tools,
            extra_env=extra_env,
            timeout_seconds=timeout_seconds,
            action=action,
        ):
            t = raw.get("type")
            if t == "system":
                emit({"kind": "system", "text": "Claude session started"})
            elif t == "error":
                had_error = str(raw.get("message") or "streaming error")
                emit({"kind": "error", "text": had_error})
            elif t == "assistant":
                msg = raw.get("message") or {}
                for block in (msg.get("content") or []):
                    btype = (block or {}).get("type")
                    if btype == "text":
                        txt = block.get("text") or ""
                        if txt.strip():
                            collected.append(txt)
                            emit({"kind": "text", "text": txt})
                    elif btype == "tool_use":
                        inp = block.get("input") or {}
                        compact = {
                            k: (
                                (str(v)[:300] + "…")
                                if isinstance(v, str) and len(str(v)) > 300
                                else v
                            )
                            for k, v in inp.items()
                        }
                        emit(
                            {
                                "kind": "tool_use",
                                "tool": block.get("name"),
                                "input": compact,
                            }
                        )
            elif t == "stream_event":
                continue
            elif t == "result":
                if not collected and raw.get("result"):
                    collected.append(str(raw["result"]))
                emit(
                    {
                        "kind": "result",
                        "cost_usd": raw.get("total_cost_usd") or raw.get("cost_usd"),
                        "duration_ms": raw.get("duration_ms"),
                        "num_turns": raw.get("num_turns"),
                    }
                )
    except Exception as exc:
        had_error = str(exc)
        emit({"kind": "error", "text": had_error})
    final = "".join(collected)
    if had_error and not final:
        raise ClaudeCodeError(had_error)
    return final
