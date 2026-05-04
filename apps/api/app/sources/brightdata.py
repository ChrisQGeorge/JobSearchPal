"""Bright Data Web Scraper API adapter (LinkedIn + Glassdoor).

Bright Data's scraper API is async / snapshot-based:

  1. POST /datasets/v3/trigger?dataset_id=<id> with input filters →
     returns {"snapshot_id": "..."} immediately.
  2. GET /datasets/v3/snapshot/<id>?format=json polls until the
     dataset is ready (HTTP 200 with JSON array on success, 202 while
     still running).

This adapter does (1) then (2) synchronously with a max wait — usually
30-90s for small queries. For larger / global queries the user may
need to poll twice (the first poll triggers + waits; the second
collects).

Authorization: Bearer token loaded from the user's `ApiCredential`
row with provider="brightdata", label="default". The user enters
their key on the Settings page.

Two kinds wrap this module:
- brightdata_linkedin: dataset_id default `gd_lpfll7v5hcqtkxl6l`
- brightdata_glassdoor: dataset_id default `gd_l7j0bx501ockwldaqf`

Defaults can be overridden via filters.dataset_id when Bright Data
ships a new dataset version. The Bright Data dashboard shows the
exact ID for each subscribed scraper."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

from app.sources._common import USER_AGENT, html_to_md, parse_iso

log = logging.getLogger(__name__)


BRIGHTDATA_API_BASE = "https://api.brightdata.com"
TRIGGER_TIMEOUT_SECONDS = 30
POLL_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 5

DEFAULT_DATASET_LINKEDIN = "gd_lpfll7v5hcqtkxl6l"
DEFAULT_DATASET_GLASSDOOR = "gd_l7j0bx501ockwldaqf"


async def _trigger(
    api_key: str,
    dataset_id: str,
    inputs: list[dict[str, Any]],
    limit_per_input: Optional[int] = None,
) -> str:
    """Kick off a snapshot, return the snapshot_id. Raises RuntimeError
    on transport / 4xx / 5xx errors with an actionable message.

    `limit_per_input` is forwarded to Bright Data's trigger so we cap
    spend at the API level, not just at ingest. If Bright Data rejects
    the param for a particular dataset, the trigger still succeeds and
    we fall back to client-side capping in the poller."""
    url = f"{BRIGHTDATA_API_BASE}/datasets/v3/trigger"
    params: dict[str, Any] = {
        "dataset_id": dataset_id,
        "include_errors": "true",
    }
    if limit_per_input is not None and limit_per_input > 0:
        params["limit_per_input"] = limit_per_input
    async with httpx.AsyncClient(
        timeout=TRIGGER_TIMEOUT_SECONDS,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    ) as client:
        try:
            resp = await client.post(url, params=params, json=inputs)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Bright Data trigger failed: {exc}") from exc
    if resp.status_code in (401, 403):
        raise RuntimeError(
            "Bright Data rejected the API key (HTTP "
            f"{resp.status_code}). Update the key on the Settings page."
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Bright Data trigger returned HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json() if resp.content else {}
    snapshot_id = body.get("snapshot_id") if isinstance(body, dict) else None
    if not snapshot_id:
        raise RuntimeError(
            f"Bright Data trigger didn't return a snapshot_id: {body!r}"
        )
    return str(snapshot_id)


async def _poll_snapshot(
    api_key: str, snapshot_id: str
) -> list[dict[str, Any]]:
    """Wait up to POLL_TIMEOUT_SECONDS for the snapshot to be ready,
    then return the parsed JSON array. Raises RuntimeError if the
    snapshot times out or errors."""
    url = f"{BRIGHTDATA_API_BASE}/datasets/v3/snapshot/{snapshot_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }
    deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        while True:
            try:
                resp = await client.get(url, params={"format": "json"})
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"Bright Data snapshot poll failed: {exc}"
                ) from exc
            if resp.status_code == 200:
                # Ready — body is the JSON array.
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise RuntimeError(
                        f"Bright Data snapshot returned non-JSON: {exc}"
                    ) from exc
                if isinstance(data, list):
                    return data
                # Some Bright Data responses wrap results in a dict.
                if isinstance(data, dict) and isinstance(data.get("data"), list):
                    return data["data"]
                raise RuntimeError(
                    f"Bright Data snapshot shape unexpected: {type(data).__name__}"
                )
            if resp.status_code == 202:
                # Still running.
                if asyncio.get_event_loop().time() >= deadline:
                    raise RuntimeError(
                        f"Bright Data snapshot {snapshot_id} not ready "
                        f"after {POLL_TIMEOUT_SECONDS}s — try Poll now "
                        "again in a minute to collect."
                    )
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    "Bright Data rejected the API key during snapshot poll."
                )
            raise RuntimeError(
                f"Bright Data snapshot poll returned HTTP {resp.status_code}: "
                f"{resp.text[:300]}"
            )


# ---------- Per-record normalizers --------------------------------------------


def _to_lead_linkedin(rec: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Map a single LinkedIn jobs record from Bright Data to the
    common RawLead shape. Bright Data field names vary slightly across
    dataset versions, so we hedge with multiple lookup keys."""
    if not isinstance(rec, dict):
        return None
    job_id = (
        rec.get("job_posting_id")
        or rec.get("id")
        or rec.get("url")
        or rec.get("job_id")
    )
    title = rec.get("job_title") or rec.get("title")
    if not job_id or not title:
        return None
    org = (
        rec.get("company_name")
        or rec.get("company")
        or rec.get("employer_name")
    )
    location = rec.get("job_location") or rec.get("location")
    body_html = rec.get("job_summary") or rec.get("description") or rec.get("job_description") or ""
    body_md = html_to_md(body_html) if body_html else None
    workplace = (
        rec.get("workplace_type")
        or rec.get("job_workplace_type")
        or rec.get("remote")
    )
    if isinstance(workplace, str):
        wl = workplace.lower()
        if "remote" in wl:
            remote = "remote"
        elif "hybrid" in wl:
            remote = "hybrid"
        elif "on-site" in wl or "onsite" in wl or "on site" in wl:
            remote = "onsite"
        else:
            remote = None
    else:
        remote = None
    return {
        "external_id": str(job_id)[:255],
        "title": str(title).strip()[:500],
        "organization_name": (str(org).strip() if org else None),
        "location": (str(location).strip() if location else None),
        "remote_policy": remote,
        "source_url": rec.get("url") or rec.get("job_url") or None,
        "description_md": body_md,
        "posted_at": parse_iso(
            rec.get("job_posted_date")
            or rec.get("posted_at")
            or rec.get("date_posted")
        ),
        "raw": rec,
    }


def _to_lead_glassdoor(rec: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not isinstance(rec, dict):
        return None
    job_id = (
        rec.get("job_id")
        or rec.get("id")
        or rec.get("url")
        or rec.get("job_listing_id")
    )
    title = rec.get("job_title") or rec.get("title")
    if not job_id or not title:
        return None
    org = (
        rec.get("company_name")
        or rec.get("employer")
        or rec.get("company")
    )
    location = rec.get("location") or rec.get("job_location")
    body_html = rec.get("description") or rec.get("job_description") or ""
    body_md = html_to_md(body_html) if body_html else None
    return {
        "external_id": str(job_id)[:255],
        "title": str(title).strip()[:500],
        "organization_name": (str(org).strip() if org else None),
        "location": (str(location).strip() if location else None),
        # Glassdoor doesn't normally tag remote/hybrid/onsite; infer
        # from title + location.
        "remote_policy": None,
        "source_url": rec.get("url") or rec.get("job_url") or None,
        "description_md": body_md,
        "posted_at": parse_iso(
            rec.get("date_posted")
            or rec.get("posted_at")
            or rec.get("job_posted_date")
        ),
        "raw": rec,
    }


# ---------- Public adapters --------------------------------------------------


def _resolve_location(filters: Optional[dict]) -> Optional[str]:
    if not isinstance(filters, dict):
        return None
    loc = filters.get("location_include") or filters.get("location")
    if isinstance(loc, str) and loc.strip():
        return loc.strip()
    if filters.get("remote_only"):
        return "Remote"
    return None


def _build_linkedin_input(
    slug_or_url: str, filters: Optional[dict]
) -> dict[str, Any]:
    """LinkedIn input: if the user pasted a search URL, send it
    verbatim; otherwise build a search URL from the keyword + location.
    The Bright Data LinkedIn dataset is URL-based — keyword/location
    fields are rejected with a validation error."""
    raw = slug_or_url.strip()
    if raw.lower().startswith(("http://", "https://")):
        return {"url": raw}
    keyword = raw
    location = _resolve_location(filters)
    qs = f"keywords={quote_plus(keyword)}"
    if location:
        qs += f"&location={quote_plus(location)}"
    return {"url": f"https://www.linkedin.com/jobs/search/?{qs}"}


def _build_glassdoor_input(
    slug_or_url: str, filters: Optional[dict]
) -> dict[str, Any]:
    """Glassdoor input: same shape as LinkedIn — URL-based.

    The error you'll see otherwise is:
      "This input should not contain a keyword field" + "url: Required field"
    """
    raw = slug_or_url.strip()
    if raw.lower().startswith(("http://", "https://")):
        return {"url": raw}
    keyword = raw
    location = _resolve_location(filters)
    qs = f"sc.keyword={quote_plus(keyword)}"
    if location:
        qs += f"&locKeyword={quote_plus(location)}&locT=N"
    return {"url": f"https://www.glassdoor.com/Job/jobs.htm?{qs}"}


async def _run_brightdata(
    *,
    dataset_id: str,
    api_key: str,
    inputs: list[dict[str, Any]],
    record_to_lead,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    snapshot_id = await _trigger(
        api_key, dataset_id, inputs, limit_per_input=limit
    )
    log.info(
        "Bright Data trigger ok dataset=%s snapshot=%s limit=%s input=%s",
        dataset_id, snapshot_id, limit, inputs[0] if inputs else None,
    )
    records = await _poll_snapshot(api_key, snapshot_id)
    out: list[dict[str, Any]] = []
    for rec in records:
        lead = record_to_lead(rec)
        if lead is not None:
            out.append(lead)
    return out


async def fetch_linkedin(
    slug_or_url: str,
    *,
    api_key: Optional[str] = None,
    filters: Optional[dict] = None,
    dataset_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    if not api_key:
        raise RuntimeError(
            "Bright Data API key required. Add one on the Settings page "
            "(provider=brightdata) and try again."
        )
    return await _run_brightdata(
        dataset_id=dataset_id or DEFAULT_DATASET_LINKEDIN,
        api_key=api_key,
        inputs=[_build_linkedin_input(slug_or_url, filters)],
        record_to_lead=_to_lead_linkedin,
        limit=limit,
    )


async def fetch_glassdoor(
    slug_or_url: str,
    *,
    api_key: Optional[str] = None,
    filters: Optional[dict] = None,
    dataset_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    if not api_key:
        raise RuntimeError(
            "Bright Data API key required. Add one on the Settings page "
            "(provider=brightdata) and try again."
        )
    return await _run_brightdata(
        dataset_id=dataset_id or DEFAULT_DATASET_GLASSDOOR,
        api_key=api_key,
        inputs=[_build_glassdoor_input(slug_or_url, filters)],
        record_to_lead=_to_lead_glassdoor,
        limit=limit,
    )
