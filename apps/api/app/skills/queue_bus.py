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


async def run_claude_to_bus(
    *,
    prompt: str,
    source: str,
    item_id: str | int,
    label: str,
    allowed_tools: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: int = 240,
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
