"""Shared helpers for source adapters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

# Full browser-mimicking User-Agent. The "compatible; JobSearchPal" form
# we used earlier passed many Cloudflare gates but not all (RemoteOK and
# a few others 302 us back to their homepage). A full Chrome-style UA
# clears every gate we've encountered. Still self-identifies as
# JobSearchPal in a comment so operators tailing their logs can see us.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "JobSearchPal/0.1 (+https://github.com/yourusername/jobsearchpal)"
)

# Browser-ish defaults sent on every adapter request. Sites that gate
# on missing Accept-Language / Accept tend to also gate on a non-
# browser UA, so we send all three together.
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/rss+xml,application/atom+xml,*/*;q=0.7"
    ),
}

# Generous timeouts split into connect/read so a slow upstream doesn't
# wedge us. ATS APIs are usually fast (<5s), but RSS feeds behind
# Cloudflare can take 10-15s on a cold cache; size accordingly.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=5.0)

# httpx will retry transport-level failures (DNS, TCP reset, etc.) but
# only when configured. We do a small manual retry around the GET so
# the next poll has a fighting chance after a transient blip.
_HTTP_RETRIES = 2

# Cap how much HTML we round-trip per posting. Most JDs are under 50KB;
# anything larger is usually an over-stuffed careers-page wrapper that
# we don't need verbatim — the JD analyzer will work fine on the
# truncated text.
MAX_DESC_BYTES = 200_000

# Markers used to detect "this isn't actually a feed/JSON, it's an
# anti-bot challenge or interstitial HTML page." Cloudflare and friends
# either redirect to / (HTML homepage) or serve a 200 with HTML.
_HTML_PROBE_TOKENS = (
    "<!doctype html",
    "<html",
    "cf-error",
    "cloudflare",
    "captcha",
    "challenge-platform",
)


def _looks_like_html(content_type: Optional[str], body: str) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    head = body[:1024].lower().lstrip()
    return any(tok in head for tok in _HTML_PROBE_TOKENS)


class UpstreamGateError(RuntimeError):
    """Raised when an adapter fetched something that *looks* successful
    (HTTP 200) but is actually a bot-gate / interstitial / homepage
    instead of the expected feed or JSON. Surfaces as a friendly
    last_error on the source row so the user can swap UA / source URL
    / etc."""


async def _request_with_retry(
    method: str,
    url: str,
    *,
    accept: Optional[str] = None,
    timeout: Optional[httpx.Timeout] = None,
) -> httpx.Response:
    """Perform a request with the shared headers, follow redirects,
    and retry transient transport failures up to _HTTP_RETRIES times."""
    headers = dict(_DEFAULT_HEADERS)
    if accept:
        headers["Accept"] = accept
    last_exc: Optional[Exception] = None
    for attempt in range(_HTTP_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=timeout or _DEFAULT_TIMEOUT,
                headers=headers,
                follow_redirects=True,
                http2=False,  # some adapters / proxies trip on h2 negotiation
            ) as client:
                resp = await client.request(method, url)
            resp.raise_for_status()
            return resp
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt >= _HTTP_RETRIES:
                raise
            continue
    # Defensive — loop only exits via return / raise above.
    raise last_exc or RuntimeError("request_with_retry exited without a response")


async def http_get_json(url: str, *, timeout: float = 20.0) -> object:
    """Single-purpose JSON GET. Adapters call this directly; the caller
    is responsible for any per-source error handling. Raises
    `httpx.HTTPError` on transport / status failure, or
    `UpstreamGateError` when the response is HTML instead of JSON."""
    resp = await _request_with_retry(
        "GET",
        url,
        accept="application/json, */*;q=0.5",
        timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=5.0),
    )
    ct = resp.headers.get("content-type", "")
    body = resp.text
    if _looks_like_html(ct, body):
        raise UpstreamGateError(
            f"Expected JSON from {url} but got HTML "
            f"(content-type='{ct}'). The site likely bot-gated us; "
            "try increasing the poll interval or using a different "
            "source URL."
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Couldn't parse JSON response from {url}: {exc}. "
            f"Body starts with: {body[:200]!r}"
        ) from exc


async def http_get_text(
    url: str,
    *,
    timeout: float = 20.0,
    expect: Optional[str] = None,
) -> str:
    """Plain-text GET. When `expect` is set (e.g. "feed" or "html"),
    we'll raise UpstreamGateError when the response shape looks wrong
    so RSS adapters don't silently swallow Cloudflare interstitials."""
    resp = await _request_with_retry(
        "GET",
        url,
        timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=5.0),
    )
    ct = resp.headers.get("content-type", "")
    body = resp.text
    if expect == "feed" and _looks_like_html(ct, body):
        raise UpstreamGateError(
            f"Expected an RSS / Atom feed from {url} but got HTML "
            f"(content-type='{ct}'). The site likely returned a "
            "bot-gate or homepage redirect — try using a "
            "browser-supplied feed URL or pasting an alternate one."
        )
    return body


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
