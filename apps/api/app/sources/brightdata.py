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
from datetime import datetime, timezone
import json
import time
import logging
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

from app.sources._common import USER_AGENT, html_to_md, parse_iso

log = logging.getLogger(__name__)


BRIGHTDATA_API_BASE = "https://api.brightdata.com"
# Discovery triggers can take a while to answer when Bright Data is busy;
# 30s produced spurious timeouts. Triggers are NEVER retried (each one
# may be billed), so be generous — this runs in the background poller.
TRIGGER_TIMEOUT_SECONDS = 180
POLL_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 5
# Keyword discovery scrapes result pages per input row — noticeably
# slower than a single-URL collect, so it gets a bigger first-wait
# budget, and a timeout parks the snapshot for resumption instead of
# failing (see SnapshotPending).
KEYWORD_WAIT_SECONDS = 240
RESUME_WAIT_SECONDS = 45

DEFAULT_DATASET_LINKEDIN = "gd_lpfll7v5hcqtkxl6l"
DEFAULT_DATASET_GLASSDOOR = "gd_l7j0bx501ockwldaqf"

# Input-row shape for keyword discovery — matches the CSV header
# Bright Data's dashboard exports for the LinkedIn jobs dataset:
#   location,keyword,country,time_range,job_type,experience_level,remote,
#   company,location_radius   (the three middle columns are optional)
KEYWORD_DISCOVERY_FIELDS = (
    "location",
    "keyword",
    "country",
    "time_range",
    "job_type",
    "experience_level",
    "remote",
    "company",
    "location_radius",
)
# LinkedIn's own filter labels (Bright Data passes them through; the
# docs confirm the `remote` set). Matching is case-insensitive and
# values are canonicalized; anything else is sent as typed.
KEYWORD_ENUMS: dict[str, tuple[str, ...]] = {
    "remote": ("Remote", "Hybrid", "On-site"),
    "job_type": ("Full-time", "Part-time", "Contract", "Temporary",
                 "Internship", "Volunteer", "Other"),
    "experience_level": ("Internship", "Entry level", "Associate",
                         "Mid-Senior level", "Director", "Executive"),
    "time_range": ("Past 24 hours", "Past week", "Past month", "Any time"),
}
KEYWORD_TIME_RANGES = ("Past 24 hours", "Past week", "Past month", "Any time")
MAX_KEYWORD_INPUT_ROWS = 50


class SnapshotPending(RuntimeError):
    """A triggered snapshot wasn't ready within the wait budget. The
    poller persists `snapshot_id` on the source and resumes collecting
    next tick instead of re-triggering (and re-paying for) the run."""

    def __init__(self, snapshot_id: str, message: str):
        super().__init__(message)
        self.snapshot_id = snapshot_id


class TriggerUnconfirmed(RuntimeError):
    """The trigger's outcome is unknown: the connection failed, timed
    out, or Bright Data answered 5xx / without a snapshot_id. Bright
    Data may still have started the collection (it has happened: a
    ConnectError on our side while the crawl ran 21 min). The poller
    never re-sends; it looks for the snapshot instead
    (find_snapshots_since)."""


def _exc_text(exc: BaseException) -> str:
    # httpx timeouts stringify to "" — always name the exception.
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def clean_keyword_inputs(rows: Any) -> list[dict[str, str]]:
    """Normalize user-supplied keyword-discovery rows: known columns
    only, everything stringified/stripped, rows without a keyword
    dropped, capped at MAX_KEYWORD_INPUT_ROWS. Shared by the API
    validators, the CSV parser, and the adapter itself."""
    out: list[dict[str, str]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        row = {
            k: str(r.get(k) if r.get(k) is not None else "").strip()[:200]
            for k in KEYWORD_DISCOVERY_FIELDS
        }
        for k, allowed in KEYWORD_ENUMS.items():
            canon = {a.lower().replace(" ", "").replace("-", ""): a for a in allowed}
            v = row[k].lower().replace(" ", "").replace("-", "")
            if v in canon:
                row[k] = canon[v]
        if not row["keyword"]:
            continue
        out.append(row)
        if len(out) >= MAX_KEYWORD_INPUT_ROWS:
            break
    return out


async def _trigger(
    api_key: str,
    dataset_id: str,
    inputs: list[dict[str, Any]],
    limit_per_input: Optional[int] = None,
    extra_params: Optional[dict[str, str]] = None,
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
    if extra_params:
        params.update(extra_params)
    # Context for every failure message: what was asked of Bright Data.
    what = (
        f"[trigger: dataset {dataset_id}, {len(inputs)} search input"
        f"{'s' if len(inputs) != 1 else ''}, limit_per_input "
        f"{params.get('limit_per_input', 'none')}"
        + (f", {', '.join(f'{k}={v}' for k, v in (extra_params or {}).items())}" if extra_params else "")
        + "]"
    )
    no_retry = "Not retried automatically (each trigger may be billed)."
    started = time.monotonic()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=60.0, read=float(TRIGGER_TIMEOUT_SECONDS), write=60.0, pool=30.0
        ),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    ) as client:
        try:
            resp = await client.post(url, params=params, json=inputs)
        except httpx.TimeoutException as exc:
            raise TriggerUnconfirmed(
                f"Bright Data didn't answer the trigger within {TRIGGER_TIMEOUT_SECONDS}s "
                f"({type(exc).__name__}). It MAY still have started the collection — check "
                "Bright Data's dashboard (Web Scraper API → Logs / Snapshots) before running "
                f"this import again. {no_retry} {what}"
            ) from exc
        except httpx.HTTPError as exc:
            raise TriggerUnconfirmed(
                f"Couldn't confirm the trigger: connection problem after "
                f"{time.monotonic() - started:.1f}s ({_exc_text(exc)}). Bright Data may "
                f"still have received it. {no_retry} {what}"
            ) from exc
    elapsed = f"after {time.monotonic() - started:.1f}s"
    body_text = (resp.text or "").strip()[:1000] or "(empty body)"
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Bright Data rejected the API key (HTTP {resp.status_code} {elapsed}): "
            f"{body_text}. Update the key on Settings → API Keys. {what}"
        )
    if resp.status_code >= 400:
        hint = (
            "Rate limited by Bright Data — wait a bit before importing again."
            if resp.status_code == 429
            else "Bright Data had a server error."
            if resp.status_code >= 500
            else "Bright Data rejected the request — usually an invalid value in one of "
            "the search rows (check location / experience / job type spellings)."
        )
        cls = TriggerUnconfirmed if resp.status_code >= 500 else RuntimeError
        raise cls(
            f"Bright Data trigger returned HTTP {resp.status_code} {elapsed}. {hint} "
            f"Response: {body_text}. {no_retry} {what}"
        )
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = body_text
    snapshot_id = body.get("snapshot_id") if isinstance(body, dict) else None
    if not snapshot_id:
        raise TriggerUnconfirmed(
            f"Bright Data accepted the trigger (HTTP {resp.status_code} {elapsed}) but "
            f"returned no snapshot_id: {str(body)[:1000]}. Check its dashboard before "
            f"importing again. {no_retry} {what}"
        )
    return str(snapshot_id)


async def _poll_snapshot(
    api_key: str,
    snapshot_id: str,
    wait_seconds: int = POLL_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Wait up to `wait_seconds` for the snapshot to be ready, then
    return the parsed JSON array. Raises SnapshotPending when the run
    is healthy but slow (caller can resume later without re-paying),
    RuntimeError on real errors."""
    url = f"{BRIGHTDATA_API_BASE}/datasets/v3/snapshot/{snapshot_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }
    deadline = asyncio.get_event_loop().time() + wait_seconds
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
                    raise SnapshotPending(
                        snapshot_id,
                        f"Bright Data snapshot {snapshot_id} not ready "
                        f"after {wait_seconds}s — collection resumes on "
                        "the next poll.",
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


# ---------- LinkedIn record → structured job fields ---------------------------
#
# Bright Data's LinkedIn records are already structured — title, company,
# full formatted description, seniority, employment type, industry,
# exact posted timestamp, sometimes a salary object. Promoting such a
# lead maps the record straight onto FetchedJobInfo fields instead of
# re-downloading the LinkedIn page (often login-walled) and LLM-parsing
# it. See linkedin_record_to_job_fields + perform_fetch(prefetched=…).

import re as _re
from urllib.parse import urlsplit, urlunsplit

_LI_EMPLOYMENT = {
    "full-time": "full_time",
    "part-time": "part_time",
    "contract": "contract",
    "temporary": "contract",
    "internship": "internship",
    "volunteer": None,
    "other": None,
}
# LinkedIn's seniority ladder → the app's experience_level enum.
# "Entry level" / "Associate" both land on junior; LinkedIn lumps
# mid and senior ICs together as "Mid-Senior level" — title keywords
# break the tie below.
_LI_SENIORITY = {
    "internship": "junior",
    "entry level": "junior",
    "associate": "junior",
    "mid-senior level": "mid",
    "director": "director",
    "executive": "cxo",
}
_TITLE_LEVEL = [
    (_re.compile(r"\b(principal|distinguished)\b", _re.I), "principal"),
    (_re.compile(r"\bstaff\b", _re.I), "staff"),
    (_re.compile(r"\b(vp|vice president)\b", _re.I), "vp"),
    (_re.compile(r"\bhead of\b", _re.I), "director"),
    # People-management titles only — "Product Manager" / "Account
    # Manager" are IC roles and must not become experience_level=manager.
    (_re.compile(r"\b(engineering|development|software|delivery|data science) manager\b", _re.I), "manager"),
    (_re.compile(r"\b(senior|sr\.?|lead)\b", _re.I), "senior"),
]
_BUTTON_RE = _re.compile(r"<button\b.*?</button>", _re.I | _re.S)
_STRONG_TRAILING_BR_RE = _re.compile(r"(?:\s*<br\s*/?>\s*)+</strong>", _re.I)
_MONEY = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s*[kK])"
_SALARY_RANGE_RE = _re.compile(
    r"\$\s?" + _MONEY + r"\s*(?:-|–|—|to)\s*\$?\s?" + _MONEY
    + r"(?:\s*(?:per|/|an?)\s*(hour|hr|year|yr|annum|month))?",
    _re.I,
)
_PERIOD_MULT = {"hour": 2080, "hr": 2080, "month": 12}


def _money(tok: str) -> Optional[float]:
    t = tok.replace(",", "").strip().lower()
    try:
        return float(t[:-1].strip()) * 1000 if t.endswith("k") else float(t)
    except ValueError:
        return None


def _annualize(lo: Optional[float], hi: Optional[float], period: str) -> tuple:
    mult = _PERIOD_MULT.get((period or "").lower().rstrip("s"), 1)
    return (
        lo * mult if lo is not None else None,
        hi * mult if hi is not None else None,
    )


def _salary_from_record(rec: dict, text: str) -> tuple:
    """(min, max, currency) — Bright Data's base_salary object when
    present, else a "$85,000 to $110,000"-style range in the text.
    Annualized; implausible values (< 1,000/yr) are discarded."""
    bs = rec.get("base_salary")
    lo = hi = None
    cur = None
    if isinstance(bs, dict):
        lo = _money(str(bs.get("min_amount"))) if bs.get("min_amount") is not None else None
        hi = _money(str(bs.get("max_amount"))) if bs.get("max_amount") is not None else None
        c = str(bs.get("currency") or "").strip()
        cur = "USD" if c in ("$", "USD", "") else c.upper()[:8]
        lo, hi = _annualize(lo, hi, str(bs.get("payment_period") or ""))
    if lo is None and hi is None:
        m = _SALARY_RANGE_RE.search(text or "")
        if m:
            lo, hi = _annualize(_money(m.group(1)), _money(m.group(2)), m.group(3) or "")
            cur = "USD"
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    if (hi or lo or 0) < 1000:
        return None, None, None
    return lo, hi, cur


def _remote_from_record(rec: dict, location: str) -> Optional[str]:
    """Explicit workplace fields and the location string only. Free-text
    guessing from the description is deliberately NOT done: phrases
    like "unless posted as a fully remote role" or "hybrid cloud"
    mislabel jobs, and a wrong "remote" makes the Jev location score
    ignore real geography. Unknown stays None."""
    for key in ("job_workplace_type", "workplace_type"):
        v = str(rec.get(key) or "").lower()
        if "remote" in v:
            return "remote"
        if "hybrid" in v:
            return "hybrid"
        if "on-site" in v or "onsite" in v:
            return "onsite"
    # NOT used: the search row's `remote` input (echoed back as
    # discovery_input / a top-level "remote" key). LinkedIn's public
    # search ignores the workplace filter (verified 2026-10-07: f_WT=1/2/3
    # return identical results), so a "Remote" row returns on-site jobs
    # too — trusting it labelled them all remote. Unknown stays None.
    if _re.search(r"\bremote\b", location or "", _re.I):
        return "remote"
    return None


def _clean_url(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    parts = urlsplit(u)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def linkedin_record_to_job_fields(rec: dict) -> Optional[dict]:
    """Map one Bright Data LinkedIn job record to FetchedJobInfo field
    names. Returns None when the record lacks a title."""
    if not isinstance(rec, dict):
        return None
    title = str(rec.get("job_title") or rec.get("title") or "").strip()
    if not title:
        return None
    html = str(rec.get("job_description_formatted") or "")
    if html.strip():
        html = _BUTTON_RE.sub("", html)
        # LinkedIn writes headings as <strong>Heading<br><br></strong>;
        # pull the breaks outside the bold so markdown gets a clean
        # "**Heading**" line (which the coverage gate reads as a heading).
        html = _STRONG_TRAILING_BR_RE.sub(r"</strong><br><br>", html)
        description = html_to_md(html)
    else:
        description = _re.sub(
            r"\s*Show more\s+Show less\s*$", "", str(rec.get("job_summary") or "")
        ).strip()
    location = str(rec.get("job_location") or rec.get("location") or "").strip()

    emp = _LI_EMPLOYMENT.get(str(rec.get("job_employment_type") or "").strip().lower())
    level = _LI_SENIORITY.get(str(rec.get("job_seniority_level") or "").strip().lower())
    for pat, lvl in _TITLE_LEVEL:
        if pat.search(title) and level in (None, "mid", "junior"):
            # A title keyword is more specific than LinkedIn's coarse
            # band — but never demote a Director/Executive band.
            level = lvl
            break

    lo, hi, cur = _salary_from_record(rec, description)
    posted = parse_iso(rec.get("job_posted_date"))

    return {
        "title": title[:255],
        "organization_name": (str(rec.get("company_name") or "").strip() or None),
        "location": location or None,
        "remote_policy": _remote_from_record(rec, location),
        "job_description": description or None,
        "salary_min": lo,
        "salary_max": hi,
        "salary_currency": cur,
        "source_platform": "linkedin",
        "source_url": _clean_url(rec.get("url") or rec.get("job_url")),
        "date_posted": posted.date().isoformat() if posted else None,
        "employment_type": emp,
        "experience_level": level,
        "organization_industry": (str(rec.get("job_industries") or "").strip() or None),
    }


def linkedin_record_extras(rec: dict) -> list[str]:
    """Human-readable facts worth keeping that have no TrackedJob column
    (applicant count, Easy Apply, external apply link, company page)."""
    out: list[str] = []
    n = rec.get("job_num_applicants")
    if isinstance(n, int) and n > 0:
        out.append(f"{n} applicants on LinkedIn")
    if rec.get("is_easy_apply"):
        out.append("LinkedIn Easy Apply")
    if rec.get("apply_link"):
        out.append(f"Apply link: {rec['apply_link']}")
    if rec.get("company_url"):
        out.append(f"Company page: {_clean_url(rec['company_url'])}")
    return out



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
    structured = linkedin_record_to_job_fields(rec)
    if structured and structured.get("job_description"):
        # Formatted HTML → markdown keeps headings and bullets (the
        # plain job_summary flattens the whole posting into one line).
        body_md = structured["job_description"]
    else:
        body_html = rec.get("job_summary") or rec.get("description") or rec.get("job_description") or ""
        body_md = html_to_md(body_html) if body_html else None
    remote = _remote_from_record(rec, str(location or ""))
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
    filters: Optional[dict] = None,
    wait_seconds: Optional[int] = None,
) -> list[dict[str, Any]]:
    # A run parked by the poller (SnapshotPending) is RESUMED — triggering
    # a fresh one here would pay for the same search twice.
    pending = (filters or {}).get("pending_snapshot_id") if isinstance(filters, dict) else None
    if isinstance(pending, str) and pending.strip():
        records = await _poll_snapshot(
            api_key, pending.strip(), wait_seconds=wait_seconds or RESUME_WAIT_SECONDS
        )
        return [lead for lead in (record_to_lead(r) for r in records) if lead is not None]
    snapshot_id = await _trigger(
        api_key, dataset_id, inputs, limit_per_input=limit
    )
    log.info(
        "Bright Data trigger ok dataset=%s snapshot=%s limit=%s input=%s",
        dataset_id, snapshot_id, limit, inputs[0] if inputs else None,
    )
    records = await _poll_snapshot(
        api_key, snapshot_id, wait_seconds=wait_seconds or POLL_TIMEOUT_SECONDS
    )
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
    wait_seconds: Optional[int] = None,
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
        filters=filters,
        wait_seconds=wait_seconds,
    )


# ---------- Keyword discovery: one call for all rows ---------------------------
#
# A saved query is triggered as ONE snapshot whose inputs are all of its
# rows, so a job several searches match is collected (and billed) once.
# Trade-off: Bright Data only delivers a snapshot when the whole run is
# ready, so leads land together at the end rather than search by search.
# (Runs started before batching used one snapshot per row; the poller
# still resumes those.) Orchestration lives in sources/poller.py
# (_poll_keyword); these are the API pieces.


def keyword_run_rows(filters: Optional[dict]) -> list[dict[str, str]]:
    """The saved query rows with the run-time time_range override
    applied (default "Past week" — "import the previous week")."""
    f = filters if isinstance(filters, dict) else {}
    rows = clean_keyword_inputs(f.get("inputs"))
    override = f.get("time_range_override")
    if isinstance(override, str) and override.strip():
        rows = [{**r, "time_range": override.strip()} for r in rows]
    return rows


def keyword_row_label(row: dict) -> str:
    bits = [row.get("keyword") or "?"]
    for k in ("location", "remote", "experience_level", "job_type"):
        if row.get(k):
            bits.append(row[k])
    return " · ".join(bits)[:120]


async def trigger_keyword_rows(
    api_key: str, rows: list[dict], *, dataset_id: Optional[str], limit: Optional[int]
) -> str:
    """ONE snapshot for all of a saved query's rows (each row is one
    input of the same call), so a job matched by several searches is
    collected once instead of once per search. `limit` is per input."""
    return await _trigger(
        api_key,
        dataset_id or DEFAULT_DATASET_LINKEDIN,
        rows,
        limit_per_input=limit,
        extra_params={"type": "discover_new", "discover_by": "keyword"},
    )


async def trigger_keyword_row(
    api_key: str, row: dict, *, dataset_id: Optional[str], limit: Optional[int]
) -> str:
    """Single-row trigger — only for resuming runs started before
    keyword queries were batched into one call."""
    return await trigger_keyword_rows(api_key, [row], dataset_id=dataset_id, limit=limit)


def _parse_when(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def find_snapshots_since(
    api_key: str, dataset_id: Optional[str], since: datetime
) -> list[dict[str, Any]]:
    """Snapshots of `dataset_id` created at/after `since` (oldest first),
    as [{id, status, created}]. Read-only and free — used to find a run
    that started even though its trigger call failed on our side."""
    async with httpx.AsyncClient(
        timeout=30,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT},
    ) as client:
        resp = await client.get(
            f"{BRIGHTDATA_API_BASE}/datasets/v3/snapshots",
            params={"dataset_id": dataset_id or DEFAULT_DATASET_LINKEDIN},
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Bright Data snapshot list returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json() if resp.content else []
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        items = body.get("data") or body.get("snapshots") or []
    else:
        items = []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sid = it.get("id") or it.get("snapshot_id")
        created = _parse_when(it.get("created") or it.get("created_at"))
        if sid and created and created >= since:
            out.append({"id": str(sid), "status": str(it.get("status") or ""), "created": created})
    out.sort(key=lambda x: x["created"])
    return out


def iter_export_records(fileobj, chunk_size: int = 1 << 20):
    """Stream records out of a Bright Data export without loading the
    whole file: a JSON array (the download format), JSON Lines / NDJSON,
    or a {"data": [...]} wrapper (read whole). `fileobj` is binary.
    Yields dicts."""
    import codecs

    dec = json.JSONDecoder()
    # Incremental: a multi-byte character split across reads stays intact.
    utf8 = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def read() -> str:
        # "" only at real EOF (a chunk ending mid-character can decode to "").
        while True:
            b = fileobj.read(chunk_size)
            if isinstance(b, str):
                return b
            text = utf8.decode(b or b"", final=not b)
            if text or not b:
                return text

    buf = read().lstrip("\ufeff").lstrip()
    while not buf:
        more = read()
        if not more:
            return
        buf = more.lstrip("\ufeff").lstrip()
    if buf[0] == "{":
        # Need the whole first line to tell JSON Lines from one object.
        while "\n" not in buf:
            more = read()
            if not more:
                break
            buf += more
        first_line = buf.split("\n", 1)[0].strip()
        try:
            first = json.loads(first_line)
            # A single-line {"data": [...]} wrapper isn't JSON Lines.
            is_jsonl = not (isinstance(first, dict) and isinstance(first.get("data"), list))
        except ValueError:
            is_jsonl = False
        if not is_jsonl:
            rest = []
            while True:
                more = read()
                if not more:
                    break
                rest.append(more)
            whole = json.loads(buf + "".join(rest))
            items = whole.get("data") if isinstance(whole, dict) else None
            if isinstance(items, list):
                yield from (r for r in items if isinstance(r, dict))
            elif isinstance(whole, dict):
                yield whole
            return
        pending = buf
        while True:
            *lines, pending = pending.split("\n")
            for line in lines:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        yield rec
            more = read()
            if not more:
                break
            pending += more
        if pending.strip():
            rec = json.loads(pending)
            if isinstance(rec, dict):
                yield rec
        return
    if buf[0] != "[":
        raise ValueError("Not a Bright Data export: expected a JSON array or JSON Lines.")
    buf, pos = buf[1:], 0
    while True:
        # Skip separators; refill when the buffer runs dry mid-record.
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,":
                pos += 1
            if pos < len(buf):
                break
            more = read()
            if not more:
                raise ValueError("Export ended before the closing ']'.")
            buf, pos = buf[pos:] + more, 0
        if buf[pos] == "]":
            return
        try:
            rec, end = dec.raw_decode(buf, pos)
        except json.JSONDecodeError:
            more = read()
            if not more:
                raise
            buf, pos = buf[pos:] + more, 0
            continue
        if isinstance(rec, dict):
            yield rec
        pos = end
        if pos > chunk_size:
            buf, pos = buf[pos:], 0


async def snapshot_status(api_key: str, snapshot_id: str) -> str:
    """starting / running / ready / failed / canceled (Bright Data's
    Monitor Progress API)."""
    async with httpx.AsyncClient(
        timeout=20,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT},
    ) as client:
        resp = await client.get(f"{BRIGHTDATA_API_BASE}/datasets/v3/progress/{snapshot_id}")
    if resp.status_code in (401, 403):
        raise RuntimeError("Bright Data rejected the API key during progress check.")
    if resp.status_code >= 400:
        raise RuntimeError(f"Bright Data progress returned HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json() if resp.content else {}
    return str((body or {}).get("status") or "running").lower()


async def download_keyword_snapshot(api_key: str, snapshot_id: str) -> list[dict[str, Any]]:
    """Leads from a ready snapshot (raises SnapshotPending if Bright Data
    is still packaging it — retried next tick)."""
    records = await _poll_snapshot(api_key, snapshot_id, wait_seconds=30)
    return [lead for lead in (_to_lead_linkedin(r) for r in records) if lead is not None]


async def fetch_glassdoor(
    slug_or_url: str,
    *,
    api_key: Optional[str] = None,
    filters: Optional[dict] = None,
    dataset_id: Optional[str] = None,
    limit: Optional[int] = None,
    wait_seconds: Optional[int] = None,
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
        filters=filters,
        wait_seconds=wait_seconds,
    )
