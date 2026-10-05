"""Agent access tokens for the MCP endpoint.

Long-lived, revocable bearer tokens that external agents present to
/api/v1/mcp. Only a SHA-256 hash is stored; the plaintext is shown once
at creation. Each token carries a scope — "read" (read tools only) or
"read_write" (everything) — and is bound to the user who minted it.

Stored in /root/.claude/jsp-mcp-tokens.json on the claude_config volume
(git-proof, survives rebuilds), like the other runtime settings.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_PATH = Path("/root/.claude/jsp-mcp-tokens.json")
_LOCK = threading.Lock()
TOKEN_PREFIX = "jspmcp_"
SCOPES = ("read", "read_write")
MAX_TOKENS = 50


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load() -> list[dict]:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return []


def _save(rows: list[dict]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    tmp.replace(_PATH)


def _public(row: dict) -> dict:
    return {k: row.get(k) for k in (
        "id", "name", "scope", "hint", "created_at", "last_used_at"
    )}


def list_tokens(user_id: int) -> list[dict]:
    return [_public(r) for r in _load() if r.get("user_id") == user_id]


def create_token(user_id: int, name: str, scope: str) -> tuple[str, dict]:
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = {
        "id": secrets.token_hex(6),
        "user_id": user_id,
        "name": (name or "agent").strip()[:80] or "agent",
        "scope": scope,
        "hash": _hash(plaintext),
        "hint": plaintext[-4:],
        "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "last_used_at": None,
    }
    with _LOCK:
        rows = _load()
        if sum(1 for r in rows if r.get("user_id") == user_id) >= MAX_TOKENS:
            raise ValueError(f"At most {MAX_TOKENS} agent tokens per user.")
        rows.append(row)
        _save(rows)
    return plaintext, _public(row)


def revoke_token(user_id: int, token_id: str) -> bool:
    with _LOCK:
        rows = _load()
        kept = [
            r for r in rows
            if not (r.get("user_id") == user_id and r.get("id") == token_id)
        ]
        if len(kept) == len(rows):
            return False
        _save(kept)
    return True


def resolve_token(token: str) -> Optional[dict]:
    """Return {user_id, scope, id, name} for a valid token, else None.
    Touches last_used_at (at most once a minute per token)."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    h = _hash(token)
    with _LOCK:
        rows = _load()
        for r in rows:
            if secrets.compare_digest(str(r.get("hash", "")), h):
                now = datetime.now(tz=timezone.utc)
                last = r.get("last_used_at")
                try:
                    stale = (
                        last is None
                        or (now - datetime.fromisoformat(last)).total_seconds() > 60
                    )
                except ValueError:
                    stale = True
                if stale:
                    r["last_used_at"] = now.isoformat(timespec="seconds")
                    try:
                        _save(rows)
                    except OSError as exc:  # pragma: no cover
                        log.warning("Could not persist MCP token usage: %s", exc)
                return {
                    "user_id": int(r["user_id"]),
                    "scope": r.get("scope", "read"),
                    "id": r.get("id"),
                    "name": r.get("name"),
                }
    return None
