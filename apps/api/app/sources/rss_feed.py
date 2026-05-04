"""Generic RSS / Atom adapter.

Treats every entry as a job lead. Best-effort field extraction:
title → title, link → source_url, summary/content → description_md.
External id falls back to entry.id, then entry.link, then a hash of the
title — feeds vary wildly so we hedge."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.sources._common import html_to_md, http_get_text, infer_remote_policy

log = logging.getLogger(__name__)


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
        raise ValueError(
            "rss source needs a full URL starting with http:// or https://."
        )
    # Two-stage fetch: pull the body with our own User-Agent first
    # (feedparser's default UA gets blocked by some Cloudflare-fronted
    # feeds), then hand the bytes to feedparser. If httpx fetch fails
    # we let the exception bubble — caller surfaces it with a friendly
    # 4xx mapping.
    text = await http_get_text(url)

    try:
        import feedparser  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "feedparser package is not installed in the API image. "
            "Rebuild the container after pulling the latest requirements."
        ) from exc

    feed = feedparser.parse(text)
    if feed.bozo and not feed.entries:
        # feedparser couldn't parse anything useful. Surface the real
        # error so the source's last_error tells the user what to fix
        # rather than just "0 leads".
        bex = getattr(feed, "bozo_exception", None)
        raise RuntimeError(
            f"Couldn't parse {url} as RSS / Atom: "
            f"{type(bex).__name__ if bex else 'unknown error'} — "
            f"{str(bex)[:200] if bex else 'no entries returned.'}"
        )
    if not feed.entries:
        log.info(
            "RSS source %s parsed cleanly but produced 0 entries.", url
        )
        return []
    out: list[dict[str, Any]] = []
    feed_title = (
        (feed.feed.get("title") if hasattr(feed.feed, "get") else None) or None
    )
    for entry in feed.entries or []:
        raw_title = (getattr(entry, "title", None) or "").strip()
        if not raw_title:
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
        # common keys; otherwise leave it empty. WeWorkRemotely's
        # custom <region> shows up on entry.region.
        location = (
            getattr(entry, "location", None)
            or getattr(entry, "region", None)
            or (entry.get("job_location") if hasattr(entry, "get") else None)
            or None
        )
        # Org-name extraction: many job-board feeds title rows as
        # "Org Name: Role Title" (WeWorkRemotely, RemoteOK, etc.). Split
        # on the first colon when the prefix is short enough to plausibly
        # be a company name. Falls back to the channel title.
        org_name = feed_title
        title = raw_title
        if ":" in raw_title:
            prefix, _, suffix = raw_title.partition(":")
            prefix = prefix.strip()
            suffix = suffix.strip()
            if 0 < len(prefix) <= 60 and suffix:
                org_name = prefix
                title = suffix
        out.append(
            {
                "external_id": _stable_id(entry),
                "title": title,
                "organization_name": org_name,
                "location": location,
                "remote_policy": infer_remote_policy(title, location, body_md),
                "source_url": link,
                "description_md": body_md,
                "posted_at": _entry_published(entry),
                "raw": {
                    "title": raw_title,
                    "link": link,
                    "summary": getattr(entry, "summary", None),
                },
            }
        )
    return out
