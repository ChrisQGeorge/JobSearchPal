"""Shared helpers for source adapters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

# Mozilla-prefixed UA so Cloudflare-fronted RSS feeds (WeWorkRemotely,
# Substack, etc.) don't 403 us. Still self-identifies as JobSearchPal so
# operators can spot us in their logs.
USER_AGENT = (
    "Mozilla/5.0 (compatible; JobSearchPal/0.1; "
    "+https://github.com/yourusername/jobsearchpal)"
)

# Cap how much HTML we round-trip per posting. Most JDs are under 50KB;
# anything larger is usually an over-stuffed careers-page wrapper that
# we don't need verbatim — the JD analyzer will work fine on the
# truncated text.
MAX_DESC_BYTES = 200_000


async def http_get_json(url: str, *, timeout: float = 20.0) -> object:
    """Single-purpose JSON GET. Adapters call this directly; the caller
    is responsible for any per-source error handling. Raises
    `httpx.HTTPError` on transport / status failure."""
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def http_get_text(url: str, *, timeout: float = 20.0) -> str:
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def html_to_md(html: str) -> str:
    """Best-effort HTML → markdown for ATS payloads. Falls back to a
    plain-text strip if html2text isn't usable for some reason."""
    if not html:
        return ""
    try:
        import html2text  # noqa: WPS433 (runtime import, optional dep)

        h = html2text.HTML2Text()
        h.body_width = 0
        h.ignore_links = False
        h.ignore_images = True
        return (h.handle(html) or "").strip()[:MAX_DESC_BYTES]
    except Exception:
        # Last-ditch strip — keep us moving even if html2text errors.
        from html.parser import HTMLParser  # noqa: WPS433

        class _Strip(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.parts: list[str] = []

            def handle_data(self, data: str) -> None:
                self.parts.append(data)

        s = _Strip()
        s.feed(html)
        return "".join(s.parts).strip()[:MAX_DESC_BYTES]


def parse_iso(value: object) -> Optional[datetime]:
    """Parse an upstream timestamp into a tz-aware datetime, or None."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        # Some feeds return milliseconds since epoch (Greenhouse / Lever).
        # Heuristic: > 1e12 means ms, otherwise seconds.
        ts = value / 1000.0 if value > 1_000_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Replace trailing Z with +00:00 so fromisoformat copes (3.10 doesn't
    # accept Z natively).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


_REMOTE_HINTS = ("remote", "anywhere", "wfh", "work from home", "distributed")
_HYBRID_HINTS = ("hybrid",)


def infer_remote_policy(*texts: Optional[str]) -> Optional[str]:
    """Infer remote_policy from any combination of upstream strings —
    the adapter passes whatever location-ish fields it has. Returns
    one of "remote" / "hybrid" / "onsite" / None."""
    bag = " ".join((t or "").lower() for t in texts if t)
    if not bag:
        return None
    if any(h in bag for h in _HYBRID_HINTS):
        return "hybrid"
    if any(h in bag for h in _REMOTE_HINTS):
        return "remote"
    # Any explicit-looking city / region string → "onsite". We don't
    # want to lie when upstream didn't actually say so, so this is
    # gated to a non-empty bag of words.
    return "onsite"
