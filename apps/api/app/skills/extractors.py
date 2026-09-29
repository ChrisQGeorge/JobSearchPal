"""Deterministic job-posting extraction — no LLM in the hot path.

Layers, tried in order per fetch (first validated result wins):

  1. Generated per-domain extractor — Python modules AUTHORED BY CLAUDE
     but executed as plain code. When the LLM fallback successfully
     parses a page from a domain we have no extractor for, an
     `extractor_gen` queue task hands Claude the raw HTML plus the
     validated field output and asks it to WRITE a module; the candidate
     is tested against that sample and only installed if its output
     matches. Future fetches of the domain are then pure code.
  2. schema.org JobPosting JSON-LD — most job boards and ATSes embed a
     machine-readable copy of the posting; parsing it is free.
  3. (caller) LLM fallback — reads the page, fills the fields, and its
     validated output becomes the ground truth for generating a module
     so the domain never needs the LLM again.

Generated modules live under /root/.claude/jsp-extractors on the
claude_config volume — OUTSIDE the git checkout by construction, so
`git pull` / image rebuilds never touch them. A registry.json tracks
per-domain state (installed, consecutive failures, last generation
failure). An extractor that fails validation 3 fetches in a row (site
redesign) is auto-disabled, which re-opens the domain for a fresh
generation pass.

Trust note: executing model-authored code is deliberate here — this is
a single-user app whose container already runs Claude with Bash, so the
boundary is unchanged. Candidates are still gated by the test harness,
run with a hard timeout, and given nothing but the HTML string.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_DIR = Path("/root/.claude/jsp-extractors")
_SAMPLES = _DIR / "samples"
_REGISTRY = _DIR / "registry.json"

# Fields a generated extractor may return — the FetchedJobInfo subset
# that's structurally extractable. Anything else is dropped.
EXTRACTOR_FIELDS = (
    "title",
    "organization_name",
    "location",
    "remote_policy",
    "employment_type",
    "salary_min",
    "salary_max",
    "salary_currency",
    "date_posted",
    "job_description",
)

# Don't retry generation for a domain that failed within this window.
_GEN_RETRY_AFTER_SECONDS = 7 * 24 * 3600
_MAX_CONSECUTIVE_FAILURES = 3
_MAX_SAMPLE_CHARS = 400_000
_MODULE_TIMEOUT_SECONDS = 10


def domain_for(url: str) -> Optional[str]:
    try:
        host = (urlparse(url).netloc or "").lower().split(":")[0]
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _module_path(domain: str) -> Path:
    return _DIR / (re.sub(r"[^a-z0-9.-]+", "_", domain) + ".py")


def _sample_paths(domain: str) -> tuple[Path, Path]:
    safe = re.sub(r"[^a-z0-9.-]+", "_", domain)
    return _SAMPLES / f"{safe}.html", _SAMPLES / f"{safe}.expected.json"


def _load_registry() -> dict:
    try:
        data = json.loads(_REGISTRY.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_registry(reg: dict) -> None:
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        _REGISTRY.write_text(json.dumps(reg, indent=2))
    except OSError as exc:
        log.warning("Could not persist extractor registry: %s", exc)


def validate_extracted(data: Optional[dict]) -> bool:
    """Minimum bar for any deterministic result: a real title and a
    substantive description. Anything less falls through to the next
    layer rather than importing a husk."""
    if not isinstance(data, dict):
        return False
    title = str(data.get("title") or "").strip()
    desc = str(data.get("job_description") or "").strip()
    return len(title) >= 3 and len(desc) >= 300


# ---------------------------------------------------------------------------
# Layer 2: schema.org JobPosting JSON-LD
# ---------------------------------------------------------------------------

_LD_SCRIPT_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def _iter_ld_objects(blob: object):
    if isinstance(blob, dict):
        yield blob
        graph = blob.get("@graph")
        if isinstance(graph, list):
            for g in graph:
                if isinstance(g, dict):
                    yield g
    elif isinstance(blob, list):
        for item in blob:
            yield from _iter_ld_objects(item)


def _ld_location(jp: dict) -> Optional[str]:
    locs = jp.get("jobLocation")
    if isinstance(locs, dict):
        locs = [locs]
    if not isinstance(locs, list):
        return None
    parts: list[str] = []
    for loc in locs[:3]:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address")
        if isinstance(addr, dict):
            bits = [
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                addr.get("addressCountry"),
            ]
            s = ", ".join(str(b).strip() for b in bits if b and str(b).strip())
            if s:
                parts.append(s)
        elif isinstance(addr, str) and addr.strip():
            parts.append(addr.strip())
    return " / ".join(dict.fromkeys(parts)) or None


def _ld_salary(jp: dict) -> tuple[Optional[float], Optional[float], Optional[str]]:
    bs = jp.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, None
    currency = bs.get("currency")
    value = bs.get("value")
    lo = hi = None
    if isinstance(value, dict):
        lo = value.get("minValue")
        hi = value.get("maxValue")
        if lo is None and hi is None:
            lo = hi = value.get("value")
    elif isinstance(value, (int, float)):
        lo = hi = value

    def _num(v: object) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return _num(lo), _num(hi), (str(currency) if currency else None)


_EMPLOYMENT_MAP = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "contract",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
}


def extract_jsonld(html: str) -> Optional[dict]:
    """Pull a schema.org JobPosting out of the page's JSON-LD, mapped to
    FetchedJobInfo-shaped keys. Returns None when absent/unusable."""
    from app.sources._common import html_to_md

    for m in _LD_SCRIPT_RE.finditer(html):
        raw = m.group(1).strip()
        try:
            blob = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for obj in _iter_ld_objects(blob):
            t = obj.get("@type")
            types = t if isinstance(t, list) else [t]
            if "JobPosting" not in [str(x) for x in types]:
                continue
            org = obj.get("hiringOrganization")
            org_name = (
                org.get("name") if isinstance(org, dict) else org
            )
            lo, hi, cur = _ld_salary(obj)
            emp_raw = obj.get("employmentType")
            if isinstance(emp_raw, list):
                emp_raw = emp_raw[0] if emp_raw else None
            employment = _EMPLOYMENT_MAP.get(str(emp_raw or "").upper())
            remote = (
                "remote"
                if str(obj.get("jobLocationType") or "").upper() == "TELECOMMUTE"
                else None
            )
            date_posted = None
            dp = str(obj.get("datePosted") or "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dp):
                date_posted = dp
            desc_html = str(obj.get("description") or "")
            data = {
                "title": str(obj.get("title") or "").strip() or None,
                "organization_name": (
                    str(org_name).strip() if org_name else None
                ),
                "location": _ld_location(obj),
                "remote_policy": remote,
                "employment_type": employment,
                "salary_min": lo,
                "salary_max": hi,
                "salary_currency": cur,
                "date_posted": date_posted,
                "job_description": html_to_md(desc_html) or None,
            }
            if validate_extracted(data):
                return data
    return None


# ---------------------------------------------------------------------------
# Layer 1: generated per-domain modules
# ---------------------------------------------------------------------------

def _run_module_sync(code: str, html: str) -> Optional[dict]:
    """Exec a module and call extract(html). Runs in a worker thread with
    the caller enforcing overall timeout via asyncio.wait_for."""
    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 — deliberate; see module docstring
    fn = namespace.get("extract")
    if not callable(fn):
        raise ValueError("module defines no extract(html) function")
    out = fn(html)
    if out is None:
        return None
    if not isinstance(out, dict):
        raise ValueError("extract() returned a non-dict")
    return {k: out.get(k) for k in EXTRACTOR_FIELDS}


async def run_generated(domain: str, html: str) -> Optional[dict]:
    """Run the installed extractor for `domain`, if any. Returns the
    extracted dict on success; None when no module, disabled, invalid
    output, or error. Failures count toward auto-disable."""
    import asyncio

    reg = _load_registry()
    entry = reg.get(domain)
    if not isinstance(entry, dict) or not entry.get("installed") or entry.get("disabled"):
        return None
    path = _module_path(domain)
    try:
        code = path.read_text()
    except OSError:
        return None
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_run_module_sync, code, html),
            timeout=_MODULE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        log.warning("Generated extractor for %s raised: %s", domain, exc)
        data = None
    if data is not None and validate_extracted(data):
        if entry.get("failures"):
            entry["failures"] = 0
            _save_registry(reg)
        return data
    # Miss — likely a site redesign. Track and auto-disable so the next
    # LLM fallback re-opens generation.
    entry["failures"] = int(entry.get("failures") or 0) + 1
    if entry["failures"] >= _MAX_CONSECUTIVE_FAILURES:
        entry["disabled"] = True
        entry["installed"] = False
        log.info(
            "Extractor for %s disabled after %d consecutive failures — "
            "will regenerate on next LLM fallback.",
            domain, entry["failures"],
        )
    _save_registry(reg)
    return None


async def deterministic_extract(
    url: str, html: str
) -> Optional[tuple[dict, str]]:
    """Try the no-LLM layers. Returns (data, engine) or None."""
    domain = domain_for(url)
    if domain:
        data = await run_generated(domain, html)
        if data is not None:
            return data, f"generated extractor ({domain})"
    data = extract_jsonld(html)
    if data is not None:
        return data, "schema.org JSON-LD"
    return None


# ---------------------------------------------------------------------------
# Generation plumbing (used by the LLM-fallback path + the worker task)
# ---------------------------------------------------------------------------

def should_generate(domain: Optional[str]) -> bool:
    """Is this domain a candidate for a new generated extractor?"""
    if not domain:
        return False
    reg = _load_registry()
    entry = reg.get(domain)
    if not isinstance(entry, dict):
        return True
    if entry.get("installed") and not entry.get("disabled"):
        return False
    last_fail = entry.get("last_gen_failure_ts")
    if isinstance(last_fail, (int, float)):
        if time.time() - last_fail < _GEN_RETRY_AFTER_SECONDS:
            return False
    return True


def save_sample(domain: str, html: str, expected: dict) -> None:
    """Persist the HTML + the LLM's validated output as the ground truth
    an extractor_gen task will build and test against."""
    html_path, exp_path = _sample_paths(domain)
    try:
        _SAMPLES.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html[:_MAX_SAMPLE_CHARS], encoding="utf-8")
        exp_path.write_text(
            json.dumps(
                {k: expected.get(k) for k in EXTRACTOR_FIELDS},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Could not save extractor sample for %s: %s", domain, exc)


def load_sample(domain: str) -> Optional[tuple[str, dict]]:
    html_path, exp_path = _sample_paths(domain)
    try:
        return html_path.read_text(encoding="utf-8"), json.loads(
            exp_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None


def _norm_text(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def test_candidate(code: str, html: str, expected: dict) -> tuple[bool, str]:
    """Run a candidate module against the sample and compare with the
    validated expected output. Pass bar: title matches (normalized),
    description present at ≥50% of the expected length, and the general
    validation gate holds."""
    try:
        data = _run_module_sync(code, html)
    except Exception as exc:
        return False, f"candidate raised: {type(exc).__name__}: {exc}"
    if data is None:
        return False, "candidate returned None on the sample page"
    if not validate_extracted(data):
        return False, "candidate output failed the validation gate"
    if _norm_text(data.get("title")) != _norm_text(expected.get("title")):
        return False, (
            f"title mismatch: {data.get('title')!r} vs expected "
            f"{expected.get('title')!r}"
        )
    exp_desc = _norm_text(expected.get("job_description"))
    got_desc = _norm_text(data.get("job_description"))
    if exp_desc and len(got_desc) < 0.5 * len(exp_desc):
        return False, (
            f"description too short: {len(got_desc)} chars vs expected "
            f"~{len(exp_desc)}"
        )
    return True, "ok"


def install_module(domain: str, code: str) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _module_path(domain).write_text(code, encoding="utf-8")
    reg = _load_registry()
    reg[domain] = {
        "installed": True,
        "disabled": False,
        "failures": 0,
        "installed_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
    }
    _save_registry(reg)
    log.info("Installed generated extractor for %s", domain)


def record_gen_failure(domain: str, reason: str) -> None:
    reg = _load_registry()
    entry = reg.get(domain)
    if not isinstance(entry, dict):
        entry = {}
    entry["last_gen_failure_ts"] = time.time()
    entry["last_gen_failure"] = reason[:500]
    reg[domain] = entry
    _save_registry(reg)
