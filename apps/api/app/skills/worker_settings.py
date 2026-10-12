"""Worker tuning knobs the user can change at runtime.

Lives in a tiny JSON file in the existing /root/.claude config volume so
the setting persists across container restarts. Re-read on every queue
worker iteration — changes from the Companion Activity page take effect
on the next claim slot opening, no API restart needed.

Single key today: `max_parallel` (how many queue tasks the worker is
allowed to run concurrently). Defaults to 1 (current sequential
behavior). The /api/v1/jobs/worker-settings endpoint reads and writes
this file.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_PATH = Path("/root/.claude/jsp-worker-settings.json")
_DEFAULT_MAX_PARALLEL = int(os.environ.get("JSP_WORKER_PARALLEL", "1"))
# Clamp range. Below 1 nothing runs. The RAM cost of a slot depends on
# what runs in it: a CLAUDE task spawns a Node CLI subprocess peaking at
# ~0.5-1 GB RSS (so N Claude slots need roughly N GB of API_MEM_LIMIT
# headroom — see docker-compose.yml), while an EXTERNAL-provider task
# (ext:deepseek/…, local Ollama, …) is just an HTTP call and costs
# almost nothing. 16 is sized for external-heavy queues; if your queue
# mixes in Claude tasks, keep the setting near API_MEM_LIMIT/1GB or
# expect OOM-killed tasks (they error + retry; the host stays fenced).
_MIN = 1
_MAX = 16


# Independent lanes. Tasks that never call an LLM get their own slots so
# they don't queue behind (or crowd out) Claude work:
#   llm   — everything that may call a model (the original max_parallel)
#   build — Bright Data lead → tracked job, built from the stored record
#   jev   — job scoring for users with a TypeSafe Jev key (one HTTP call)
LANES = ("llm", "build", "jev")
_LANE_KEY = {"llm": "max_parallel", "build": "max_parallel_build", "jev": "max_parallel_jev"}
_LANE_DEFAULT = {"llm": _DEFAULT_MAX_PARALLEL, "build": 4, "jev": 4}


def _read() -> dict:
    try:
        data = json.loads(_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return {}


def get_lane_limit(lane: str) -> int:
    """Persisted limit for a lane, clamped; env / built-in default on any
    file problem so the worker never refuses to run."""
    try:
        n = int(_read().get(_LANE_KEY[lane], _LANE_DEFAULT[lane]))
    except (KeyError, TypeError, ValueError):
        n = _LANE_DEFAULT.get(lane, 1)
    return max(_MIN, min(_MAX, n))


def get_lane_limits() -> dict[str, int]:
    return {lane: get_lane_limit(lane) for lane in LANES}


def set_lane_limits(limits: dict[str, int]) -> dict[str, int]:
    """Persist any subset of lane limits (others keep their value)."""
    data = _read()
    for lane, n in limits.items():
        if lane in _LANE_KEY and n is not None:
            data[_LANE_KEY[lane]] = max(_MIN, min(_MAX, int(n)))
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(data))
    except OSError as exc:
        log.warning("Failed to persist worker settings: %s", exc)
    return get_lane_limits()


def get_max_parallel() -> int:
    """The LLM lane's limit (the original single setting)."""
    return get_lane_limit("llm")


def set_max_parallel(n: int) -> int:
    """Persist the LLM lane's limit. Returns the saved (clamped) value."""
    return set_lane_limits({"llm": n})["llm"]


def get_bounds() -> tuple[int, int]:
    """Expose the clamp range to the UI so the input can validate locally."""
    return (_MIN, _MAX)
