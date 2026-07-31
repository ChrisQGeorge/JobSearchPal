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
# Clamp range. Below 1 nothing runs. Each Claude subprocess is a Node
# process peaking at ~0.5-1 GB RSS with heavy CPU bursts — at the old
# ceiling of 8, a queue drain could flatten the whole host (the api
# container's default memory fence is 3g; see docker-compose.yml). 4
# already saturates a typical single-user box; raise API_MEM_LIMIT
# before raising this.
_MIN = 1
_MAX = 4


def get_max_parallel() -> int:
    """Read the persisted limit. Falls back to the env default on any
    file / parse error so the worker never refuses to run."""
    try:
        data = json.loads(_PATH.read_text())
        n = int(data.get("max_parallel", _DEFAULT_MAX_PARALLEL))
        return max(_MIN, min(_MAX, n))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return max(_MIN, min(_MAX, _DEFAULT_MAX_PARALLEL))


def set_max_parallel(n: int) -> int:
    """Persist a new limit. Returns the value actually saved after
    clamping into [_MIN, _MAX]."""
    clamped = max(_MIN, min(_MAX, int(n)))
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps({"max_parallel": clamped}))
    except OSError as exc:
        log.warning("Failed to persist worker settings: %s", exc)
    return clamped


def get_bounds() -> tuple[int, int]:
    """Expose the clamp range to the UI so the input can validate locally."""
    return (_MIN, _MAX)
