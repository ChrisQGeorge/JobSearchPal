"""Ashby job-board adapter.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true

Returns `{ apiVersion, jobs: [...] }`. Slug examples: `ramp`, `notion`."""
from __future__ import annotations

import re
from typing import Any

from app.sources._common import (
    html_to_md,
    http_get_json,
    infer_remote_policy,
    parse_iso,
)


async def fetch(slug_or_url: str) -> list[dict[str, Any]]:
    slug = slug_or_url.strip().strip("/")
    m = re.match(r"https?://jobs\.ashbyhq\.com/([^/]+)", slug)
    if m:
        slug = m.group(1)
    url = (
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        "?includeCompensation=true"
    )
    payload = await http_get_json(url)
    if not isinstance(payload, dict):
        return []
    company = slug.replace("-", " ").title() or None
    out: list[dict[str, Any]] = []
    for j in payload.get("jobs") or []:
        if not isinstance(j, dict):
            continue
        ext_id = str(j.get("id") or "").strip()
        title = (j.get("title") or "").strip()
        if not ext_id or not title:
            continue
        location = j.get("location") or j.get("locationName") or None
        # Ashby exposes per-job remote flags; map them onto our enum.
        is_remote = bool(j.get("isRemote"))
        is_hybrid = False
        # Some payloads include `secondaryLocations` / `employmentType`.
        commitment = j.get("employmentType") or None
        body_md = (
            html_to_md(j.get("descriptionHtml") or "")
            or (j.get("descriptionPlain") or "").strip()
        )
        out.append(
            {
                "external_id": ext_id,
                "title": title,
                "organization_name": company,
                "location": location,
                "remote_policy": (
                    "remote"
                    if is_remote
                    else "hybrid"
                    if is_hybrid
                    else infer_remote_policy(location, commitment)
                ),
                "source_url": j.get("jobUrl") or j.get("applyUrl") or None,
                "description_md": body_md,
                "posted_at": parse_iso(j.get("publishedAt") or j.get("updatedAt")),
                "raw": j,
            }
        )
    return out
