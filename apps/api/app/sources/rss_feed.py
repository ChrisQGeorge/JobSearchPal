"""Generic RSS / Atom adapter.

Treats every entry as a job lead. Best-effort field extraction:
title → title, link → source_url, summary/content → description_md.
External id falls back to entry.id, then entry.link, then a hash of the
title — feeds vary wildly so we hedge."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from app.sources._common import html_to_md, http_get_text, infer_remote_policy


def _stable_id(entry: Any) -> str:
    raw = (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
        or getattr(entry, "link", None)
        or getattr(entry, "title", None)
        or ""
    )
    raw = str(raw).strip()
    if not raw:
        raw = repr(entry)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def _entry_published(entry: Any) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            try:
                return datetime(*struct[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


async def fetch(slug_or_url: str) -> list[dict[str, Any]]:
    url = slug_or_url.strip()
    if not url.startswith("http"):
        return []
    text = await http_get_text(url)
    # feedparser is sync — parse the already-downloaded body.
    import feedparser  # type: ignore

    feed = feedparser.parse(text)
    out: list[dict[str, Any]] = []
    feed_title = (
        (feed.feed.get("title") if hasattr(feed.feed, "get") else None) or None
    )
    for entry in feed.entries or []:
        title = (getattr(entry, "title", None) or "").strip()
        if not title:
            continue
        link = getattr(entry, "link", None) or None
        # Body: prefer entry.content (Atom), fall back to summary (RSS).
        body_html = ""
        contents = getattr(entry, "content", None)
        if contents:
            for c in contents:
                v = c.get("value") if isinstance(c, dict) else getattr(c, "value", None)
                if v:
                    body_html += v
        if not body_html:
            body_html = getattr(entry, "summary", "") or ""
        body_md = html_to_md(body_html) if body_html else None
        # Generic feeds rarely tag location explicitly. Try a couple of
        # common keys; otherwise leave it empty.
        location = (
            getattr(entry, "location", None)
            or (entry.get("job_location") if hasattr(entry, "get") else None)
            or None
        )
        out.append(
            {
                "external_id": _stable_id(entry),
                "title": title,
                "organization_name": feed_title,
                "location": location,
                "remote_policy": infer_remote_policy(title, location, body_md),
                "source_url": link,
                "description_md": body_md,
                "posted_at": _entry_published(entry),
                "raw": {
                    "title": title,
                    "link": link,
                    "summary": getattr(entry, "summary", None),
                },
            }
        )
    return out
