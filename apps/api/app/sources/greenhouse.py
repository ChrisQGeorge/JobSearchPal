"""Greenhouse boards-api adapter.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

`?content=true` returns the JD body inline (HTML) so we don't have to
follow per-job links. Public, no auth, no rate-limit hassle for normal
polling cadences. Slug examples: airbnb, stripe, doordash."""
from __future__ import annotations

import re
from typing import Any

from app.sources._common import (
    html_to_md,
    http_get_json,
    infer_remote_policy,
    parse_iso,
)


def _company_from_payload(payload: dict[str, Any], slug: str) -> str | None:
    meta = payload.get("meta") or {}
    name = (meta.get("title") or "").strip()
    if name:
        return name
    return slug.replace("-", " ").title() or None


async def fetch(slug_or_url: str) -> list[dict[str, Any]]:
    slug = slug_or_url.strip().strip("/")
    # Be lenient if the user pastes the full board URL.
    m = re.match(r"https?://boards\.greenhouse\.io/([^/]+)", slug)
    if m:
        slug = m.group(1)
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    payload = await http_get_json(url)
    if not isinstance(payload, dict):
        return []
    company = _company_from_payload(payload, slug)
    out: list[dict[str, Any]] = []
    for j in payload.get("jobs") or []:
        if not isinstance(j, dict):
            continue
        ext_id = str(j.get("id") or "").strip()
        title = (j.get("title") or "").strip()
        if not ext_id or not title:
            continue
        loc_obj = j.get("location") or {}
        location = (
            loc_obj.get("name") if isinstance(loc_obj, dict) else None
        ) or None
        offices = j.get("offices") or []
        office_names = [
            o.get("name") for o in offices if isinstance(o, dict) and o.get("name")
        ]
        out.append(
            {
                "external_id": ext_id,
                "title": title,
                "organization_name": company,
                "location": location,
                "remote_policy": infer_remote_policy(location, *office_names),
                "source_url": j.get("absolute_url") or None,
                "description_md": html_to_md(j.get("content") or ""),
                "posted_at": parse_iso(j.get("updated_at") or j.get("first_published")),
                "raw": j,
            }
        )
    return out
