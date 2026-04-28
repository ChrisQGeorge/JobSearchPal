"""ATS / RSS adapters for the job-source ingest pipeline.

Each adapter's `fetch(slug_or_url)` returns a list of `RawLead` dicts.
The fields are normalized so the poller can write a single `JobLead`
row regardless of source. None means "not provided by upstream"; the
poller / JD-analyzer can backfill later.

`RawLead` shape:
    {
        "external_id":      str,    # stable upstream id, required
        "title":             str,
        "organization_name": str | None,
        "location":          str | None,
        "remote_policy":     str | None,   # onsite / hybrid / remote / null
        "source_url":        str | None,
        "description_md":    str | None,   # plaintext or markdown
        "posted_at":         datetime | None,
        "raw":               dict,         # the original payload, for audit
    }
"""
from __future__ import annotations

from typing import Awaitable, Callable

from app.sources import ashby, greenhouse, lever, rss_feed, workable, yc

RawLead = dict
Adapter = Callable[[str], Awaitable[list[RawLead]]]

ADAPTERS: dict[str, Adapter] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "workable": workable.fetch,
    "rss": rss_feed.fetch,
    "yc": yc.fetch,
}

KIND_LABELS: dict[str, str] = {
    "greenhouse": "Greenhouse (boards-api.greenhouse.io)",
    "lever": "Lever (api.lever.co)",
    "ashby": "Ashby (api.ashbyhq.com)",
    "workable": "Workable (apply.workable.com)",
    "rss": "Generic RSS / Atom feed",
    "yc": "Y Combinator Jobs RSS",
}

KIND_HINTS: dict[str, str] = {
    "greenhouse": "Company slug (e.g. `airbnb` from boards.greenhouse.io/airbnb).",
    "lever": "Company slug (e.g. `netflix` from jobs.lever.co/netflix).",
    "ashby": "Job-board slug (e.g. `ramp` from jobs.ashbyhq.com/ramp).",
    "workable": "Account subdomain (e.g. `loom` from apply.workable.com/loom).",
    "rss": "Full RSS / Atom feed URL.",
    "yc": "Full URL to a Y Combinator jobs RSS feed.",
}


__all__ = ["ADAPTERS", "KIND_LABELS", "KIND_HINTS", "RawLead", "Adapter"]
