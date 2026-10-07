"""Live preview of a job's posting page for the job detail screen.

Most job boards (LinkedIn, Indeed, many ATSes) forbid being framed
(X-Frame-Options / CSP frame-ancestors), so an <iframe> of the apply
link usually renders blank. Instead the server fetches the page and
returns:

  - `embeddable`: whether the site allows framing (the UI then shows
    the real page in an iframe as well),
  - `text`: a readable markdown copy of the posting,
  - `arrangement`: work-arrangement signals found in the text (remote /
    hybrid / on-site) with the sentences they came from — the reason
    this exists: imported listings often claim "remote" when the
    posting says otherwise.

Read-only GET of a URL the user saved on their own job. Private /
loopback / link-local hosts are refused (no probing the internal
network through this endpoint). Results are cached briefly per URL.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from typing import Any, Optional
from urllib.parse import urlparse

MAX_BYTES = 3_000_000
MAX_TEXT = 60_000
CACHE_TTL = 30 * 60
_CACHE: dict[str, tuple[float, dict]] = {}

# Signal → patterns (case-insensitive, word-bounded).
_SIGNALS: dict[str, list[str]] = {
    "onsite": [
        r"on[\s-]?site", r"in[\s-]office", r"in[\s-]person", r"office[\s-]based",
        r"must (?:be able to )?(?:commute|report)", r"\d\s*days? (?:a|per) week in (?:the )?office",
        r"not (?:a )?remote", r"no remote",
    ],
    "hybrid": [r"hybrid"],
    "remote": [r"remote", r"work from home", r"wfh", r"distributed team", r"anywhere in the"],
}
_COMPILED = {k: re.compile(r"(?i)(?<![a-z])(?:" + "|".join(v) + r")(?![a-z])") for k, v in _SIGNALS.items()}


class PreviewError(RuntimeError):
    pass


async def _check_host(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise PreviewError("Not an http(s) URL.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(u.hostname, None)
    except socket.gaierror as exc:
        raise PreviewError(f"Can't resolve {u.hostname}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise PreviewError(f"{u.hostname} resolves to a private address — not fetched.")


def _frame_policy(headers) -> tuple[bool, str]:
    """(embeddable, reason) from X-Frame-Options / CSP frame-ancestors."""
    xfo = (headers.get("x-frame-options") or "").strip().lower()
    if xfo in ("deny", "sameorigin") or xfo.startswith("allow-from"):
        return False, f"the site sends X-Frame-Options: {xfo.upper()}"
    csp = headers.get("content-security-policy") or ""
    m = re.search(r"frame-ancestors([^;]*)", csp, re.I)
    if m:
        val = m.group(1).strip()
        if val in ("'none'", "'self'") or "*" not in val:
            return False, f"the site's CSP restricts framing (frame-ancestors {val or 'none'})"
    return True, ""


def _sentences_with(text: str, rx: re.Pattern, limit: int = 4) -> list[str]:
    out: list[str] = []
    for m in rx.finditer(text):
        start = max(text.rfind("\n", 0, m.start()), text.rfind(". ", 0, m.start()) + 1, m.start() - 160)
        end_candidates = [i for i in (text.find("\n", m.end()), text.find(". ", m.end())) if i != -1]
        end = min(end_candidates + [m.end() + 160])
        snippet = re.sub(r"\s+", " ", text[max(0, start):end]).strip(" .*#-_|")
        if snippet and snippet not in out:
            out.append(snippet[:300])
        if len(out) >= limit:
            break
    return out


def detect_arrangement(text: str) -> dict[str, Any]:
    """Signals + a best guess. On-site wording outranks a bare "remote"
    mention (postings often say "this is not a remote role" or list
    remote benefits for other teams); hybrid outranks remote."""
    found = {k: _sentences_with(text, rx) for k, rx in _COMPILED.items()}
    found = {k: v for k, v in found.items() if v}
    if "onsite" in found and "hybrid" not in found and "remote" not in found:
        guess = "onsite"
    elif "hybrid" in found:
        guess = "hybrid"
    elif "onsite" in found and "remote" in found:
        guess = "mixed"
    elif "remote" in found:
        guess = "remote"
    else:
        guess = None
    return {"guess": guess, "signals": found}


async def fetch_preview(url: str) -> dict[str, Any]:
    url = (url or "").strip()
    hit = _CACHE.get(url)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return {**hit[1], "cached": True}

    import httpx

    from app.skills.fetch_templates import extract_relevant_html
    from app.sources._common import _DEFAULT_HEADERS, html_to_md

    started = time.monotonic()
    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0),
        follow_redirects=False,  # followed by hand: every hop is host-checked
    ) as client:
        target = url
        try:
            for _hop in range(6):
                await _check_host(target)
                async with client.stream("GET", target) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        target = str(resp.url.join(resp.headers["location"]))
                        continue
                    chunks, size = [], 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            break
                        chunks.append(chunk)
                    status = resp.status_code
                    headers = resp.headers
                    final_url = str(resp.url)
                    encoding = resp.encoding or "utf-8"
                    break
            else:
                raise PreviewError("Too many redirects.")
        except httpx.HTTPError as exc:
            raise PreviewError(
                f"Couldn't load the posting ({type(exc).__name__}: {str(exc).strip() or 'no detail'})."
            ) from exc
    raw = b"".join(chunks).decode(encoding, errors="replace")
    embeddable, frame_reason = _frame_policy(headers)
    ctype = headers.get("content-type", "")
    if "html" in ctype or raw.lstrip()[:1] == "<":
        text = html_to_md(extract_relevant_html(final_url, raw)) or html_to_md(raw)
    else:
        text = raw
    text = text[:MAX_TEXT]
    out = {
        "url": url,
        "final_url": final_url,
        "status": status,
        "ok": status < 400,
        "embeddable": embeddable and status < 400,
        "frame_reason": frame_reason,
        "text": text,
        "thin": len(text.strip()) < 400,  # JS-rendered shell / bot wall
        "arrangement": detect_arrangement(text),
        "fetched_ms": int((time.monotonic() - started) * 1000),
        "cached": False,
    }
    _CACHE[url] = (time.monotonic(), out)
    if len(_CACHE) > 200:
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:50]:
            _CACHE.pop(k, None)
    return out


def invalidate(url: Optional[str]) -> None:
    if url:
        _CACHE.pop(url.strip(), None)
