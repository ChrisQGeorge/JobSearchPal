"""Saved keyword filters for the leads inbox.

Each filter targets ONE field (title / organization / location /
description) with a list of keywords (any one matches), and has a mode:
  off      — saved but not applied
  include  — show only leads that match
  exclude  — hide leads that match
Active filters stack (every include must match, no exclude may match).
Keywords match as whole words, case-insensitively: "Sr" matches "Sr.",
"SR" and "Sr Engineer" but not "Srinivas"; a title filter never looks at
the company name. Matching runs in MySQL (REGEXP_LIKE, ICU) so it covers
every lead, not just the loaded page — see keyword_condition().

Stored per user in /root/.claude/jsp-lead-filters.json (claude_config
volume), like the other runtime settings.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Optional

_PATH = Path("/root/.claude/jsp-lead-filters.json")
_LOCK = threading.Lock()
FIELDS = ("title", "organization_name", "location", "description_md")
MODES = ("off", "include", "exclude")
MAX_FILTERS = 50
MAX_KEYWORDS = 200


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _clean(f: Any) -> Optional[dict]:
    if not isinstance(f, dict):
        return None
    field = f.get("field") if f.get("field") in FIELDS else "title"
    mode = f.get("mode") if f.get("mode") in MODES else "off"
    seen: set[str] = set()
    keywords: list[str] = []
    for k in f.get("keywords") or []:
        k = re.sub(r"\s+", " ", str(k)).strip()[:80]
        if k and k.lower() not in seen:
            seen.add(k.lower())
            keywords.append(k)
    return {
        "id": str(f.get("id") or secrets.token_hex(4))[:16],
        "name": (str(f.get("name") or "").strip() or "Filter")[:60],
        "field": field,
        "mode": mode,
        "keywords": keywords[:MAX_KEYWORDS],
    }


def get_filters(user_id: int) -> list[dict]:
    raw = _load().get(str(user_id)) or []
    return [c for c in (_clean(f) for f in raw) if c is not None]


def save_filters(user_id: int, filters: list[Any]) -> list[dict]:
    cleaned = [c for c in (_clean(f) for f in filters) if c is not None][:MAX_FILTERS]
    with _LOCK:
        data = _load()
        data[str(user_id)] = cleaned
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
    return cleaned


def keyword_pattern(keywords: list[str]) -> Optional[str]:
    """One whole-word alternation for all keywords. Boundaries are
    "no letter/digit on either side" rather than \\b, so keywords with
    punctuation (C++, .NET, Sr.) still match; spaces inside a keyword
    match any whitespace run."""
    parts = []
    for k in keywords:
        k = k.strip()
        if not k:
            continue
        esc = re.escape(k).replace(r"\ ", r"\s+")
        parts.append(esc)
    if not parts:
        return None
    return r"(?<![A-Za-z0-9])(" + "|".join(parts) + r")(?![A-Za-z0-9])"


def keyword_condition(column, keywords: list[str]):
    """SQLAlchemy boolean: column contains any keyword (whole word,
    case-insensitive). NULL counts as "no match" (coalesced to '')."""
    from sqlalchemy import func

    pat = keyword_pattern(keywords)
    if pat is None:
        return None
    return func.coalesce(column, "").regexp_match(pat, flags="i")
