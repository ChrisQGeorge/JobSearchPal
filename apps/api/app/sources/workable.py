"""Workable accounts adapter.

Endpoint: https://apply.workable.com/api/v3/accounts/{slug}/jobs

Returns `{ results: [...] }`. Slug is the company subdomain on
apply.workable.com (e.g. `loom`)."""
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
    m = re.match(r"https?://apply\.workable\.com/([^/]+)", slug)
    if m:
        slug = m.group(1)
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    payload = await http_get_json(url)
    if not isinstance(payload, dict):
        return []
    company = slug.replace("-", " ").title() or None
    out: list[dict[str, Any]] = []
    for j in payload.get("results") or []:
        if not isinstance(j, dict):
            continue
        ext_id = str(j.get("shortcode") or j.get("id") or "").strip()
        title = (j.get("title") or "").strip()
        if not ext_id or not title:
            continue
        loc_obj = j.get("location") or {}
        if isinstance(loc_obj, dict):
            location_parts = [
                loc_obj.get("city"),
                loc_obj.get("region"),
                loc_obj.get("country"),
            ]
            location = ", ".join(p for p in location_parts if p) or None
        else:
            location = None
        is_remote = bool(j.get("remote") or j.get("telecommuting"))
        body_md = (
            html_to_md(j.get("description") or j.get("full_description") or "")
            or (j.get("requirements") or "").strip()
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
                    else infer_remote_policy(location)
                ),
                "source_url": j.get("url") or j.get("application_url") or None,
                "description_md": body_md,
                "posted_at": parse_iso(j.get("published_on") or j.get("created_at")),
                "raw": j,
            }
        )
    return out
