"""Persistence layer for the Claude Code long-lived OAuth token.

`claude setup-token` prints a token that the CLI expects you to export as
`CLAUDE_CODE_OAUTH_TOKEN`. Since we have no shell to export it in, we stash
the token in the container's isolated claude_config volume and inject it into
every `claude -p` subprocess invocation (see `runner.py`).

Lives at `/root/.claude/jsp-oauth-token`. Mode 0600. Nothing else writes there.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_TOKEN_PATH = Path("/root/.claude/jsp-oauth-token")


def save_token(token: str) -> None:
    token = token.strip()
    if not token:
        raise ValueError("empty token")
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(token)
    try:
        os.chmod(_TOKEN_PATH, 0o600)
    except OSError:
        pass  # best-effort; fs may not support mode bits


def load_token() -> Optional[str]:
    try:
        data = _TOKEN_PATH.read_text().strip()
        return data or None
    except FileNotFoundError:
        return None
    except OSError:
        return None


def clear_token() -> None:
    try:
        _TOKEN_PATH.unlink()
    except FileNotFoundError:
        pass


def has_token() -> bool:
    return load_token() is not None
