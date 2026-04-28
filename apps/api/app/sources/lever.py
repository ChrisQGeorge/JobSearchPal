"""Lever public postings adapter.

Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json

Returns a flat list of postings. `slug` is the company subdomain — e.g.
`netflix` (jobs.lever.co/netflix) or `figma`. Public + unauthenticated.
"""
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
    m = re.match(r"https?://jobs\.lever\.co/([^/]+)", slug)
    if m:
        slug = m.group(1)
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    payload = await http_get_json(url)
    if not isinstance(payload, list):
        return []
    company = slug.replace("-", " ").title() or None
    out: list[dict[str, Any]] = []
    for j in payload:
        if not isinstance(j, dict):
            continue
        ext_id = str(j.get("id") or "").strip()
        title = (j.get("text") or "").strip()
        if not ext_id or not title:
            continue
        cats = j.get("categories") or {}
        location = (cats.get("location") if isinstance(cats, dict) else None) or None
        commitment = (
            cats.get("commitment") if isinstance(cats, dict) else None
        ) or None
        # Lever puts a "workplaceType" on newer postings: remote / hybrid / onsite.
        workplace = j.get("workplaceType")
        # Body — descriptionPlain when present, else strip HTML from description.
        body_md = (
            j.get("descriptionPlain")
            or html_to_md(j.get("description") or "")
        )
        # Append "lists" (responsibilities / requirements) if present.
        for lst in j.get("lists") or []:
            if not isinstance(lst, dict):
                continue
            heading = (lst.get("text") or "").strip()
            content = html_to_md(lst.get("content") or "")
            if heading and content:
                body_md = f"{body_md}\n\n## {heading}\n\n{content}"
        out.append(
            {
                "external_id": ext_id,
                "title": title,
                "organization_name": company,
                "location": location,
                "remote_policy": (
                    workplace.lower()
                    if isinstance(workplace, str) and workplace
                    else infer_remote_policy(location, commitment)
                ),
                "source_url": j.get("hostedUrl") or j.get("applyUrl") or None,
                "description_md": body_md,
                "posted_at": parse_iso(j.get("createdAt")),
                "raw": j,
            }
        )
    return out
