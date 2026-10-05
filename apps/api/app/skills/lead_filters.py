"""Saved keyword filters for the leads inbox.

A filter is a named group of CONDITIONS. Each condition targets one
field (title / organization / location / description) with any number
of keywords (any one keyword satisfies the condition). The filter's
`match` decides how its conditions combine:
  all — every condition must hold (title has "AI" AND company is
        Anthropic or OpenAI)
  any — at least one condition holds
and its mode decides what happens to matching leads:
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
MATCHES = ("all", "any")
MAX_FILTERS = 50
MAX_KEYWORDS = 500
MAX_CONDITIONS = 10


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _clean_keywords(raw: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in raw or []:
        k = re.sub(r"\s+", " ", str(k)).strip()[:80]
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out[:MAX_KEYWORDS]


def _clean(f: Any) -> Optional[dict]:
    if not isinstance(f, dict):
        return None
    raw_conds = f.get("conditions")
    if not isinstance(raw_conds, list):
        # Pre-conditions shape: one field + keywords on the filter itself.
        raw_conds = [{"field": f.get("field"), "keywords": f.get("keywords")}]
    conditions = [
        {
            "field": c.get("field") if c.get("field") in FIELDS else "title",
            "keywords": _clean_keywords(c.get("keywords")),
        }
        for c in raw_conds
        if isinstance(c, dict)
    ][:MAX_CONDITIONS] or [{"field": "title", "keywords": []}]
    return {
        "id": str(f.get("id") or secrets.token_hex(4))[:16],
        "name": (str(f.get("name") or "").strip() or "Untitled filter")[:60],
        "mode": f.get("mode") if f.get("mode") in MODES else "off",
        "match": f.get("match") if f.get("match") in MATCHES else "all",
        # Newly imported leads matching this filter are stored already
        # dismissed (independent of `mode`, which only affects viewing).
        "auto_dismiss": bool(f.get("auto_dismiss")),
        "conditions": conditions,
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


def compile_matcher(flt: dict):
    """Python twin of filter_condition() for leads that aren't in the
    database yet (import time): returns `match(lead_dict) -> bool`, with
    patterns compiled once so a batch of thousands is a few in-memory
    regex checks per lead. `lead` uses the JobLead column names. Same
    whole-word pattern; Python's re and MySQL's ICU agree on everything
    keyword_pattern() emits."""
    conds = [
        (cond["field"], re.compile(pat, re.I))
        for cond in flt["conditions"]
        if (pat := keyword_pattern(cond["keywords"])) is not None
    ]
    combine = all if flt["match"] == "all" else any

    def match(lead: dict) -> bool:
        if not conds:
            return False
        return combine(rx.search(str(lead.get(field) or "")) is not None for field, rx in conds)

    return match


def lead_matches(flt: dict, lead: dict) -> bool:
    return compile_matcher(flt)(lead)


def auto_dismiss_filters(user_id: int) -> list[dict]:
    return [
        f for f in get_filters(user_id)
        if f["auto_dismiss"] and any(c["keywords"] for c in f["conditions"])
    ]


def filter_condition(model, flt: dict):
    """The whole filter as one SQLAlchemy boolean (conditions combined
    with AND for match="all", OR for "any"). Conditions with no
    keywords are ignored; a filter with none yields None (not applied)."""
    from sqlalchemy import and_, or_

    parts = [
        c for c in (
            keyword_condition(getattr(model, cond["field"]), cond["keywords"])
            for cond in flt["conditions"]
        ) if c is not None
    ]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return and_(*parts) if flt["match"] == "all" else or_(*parts)
