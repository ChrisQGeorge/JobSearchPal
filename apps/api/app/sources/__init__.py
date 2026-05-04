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

from typing import Any, Awaitable, Callable

from app.sources import ashby, brightdata, greenhouse, lever, rss_feed, workable, yc

RawLead = dict
# Adapter contract: takes the source's slug_or_url plus a context dict
# that may include `api_key`, `filters`, `dataset_id` (only populated
# when the kind needs them — ATS / RSS adapters ignore the ctx).
Adapter = Callable[[str, dict[str, Any]], Awaitable[list[RawLead]]]


def _wrap_simple(fn: Callable[[str], Awaitable[list[RawLead]]]) -> Adapter:
    """Adapt a single-arg adapter to the new (slug, ctx) contract so
    existing greenhouse / lever / etc. modules don't have to change."""

    async def _impl(slug_or_url: str, ctx: dict[str, Any]) -> list[RawLead]:
        return await fn(slug_or_url)

    return _impl


async def _brightdata_linkedin_adapter(
    slug_or_url: str, ctx: dict[str, Any]
) -> list[RawLead]:
    return await brightdata.fetch_linkedin(
        slug_or_url,
        api_key=ctx.get("api_key"),
        filters=ctx.get("filters"),
        dataset_id=ctx.get("dataset_id"),
    )


async def _brightdata_glassdoor_adapter(
    slug_or_url: str, ctx: dict[str, Any]
) -> list[RawLead]:
    return await brightdata.fetch_glassdoor(
        slug_or_url,
        api_key=ctx.get("api_key"),
        filters=ctx.get("filters"),
        dataset_id=ctx.get("dataset_id"),
    )


ADAPTERS: dict[str, Adapter] = {
    "greenhouse": _wrap_simple(greenhouse.fetch),
    "lever": _wrap_simple(lever.fetch),
    "ashby": _wrap_simple(ashby.fetch),
    "workable": _wrap_simple(workable.fetch),
    "rss": _wrap_simple(rss_feed.fetch),
    "yc": _wrap_simple(yc.fetch),
    "brightdata_linkedin": _brightdata_linkedin_adapter,
    "brightdata_glassdoor": _brightdata_glassdoor_adapter,
}

KIND_LABELS: dict[str, str] = {
    "greenhouse": "Greenhouse (boards-api.greenhouse.io)",
    "lever": "Lever (api.lever.co)",
    "ashby": "Ashby (api.ashbyhq.com)",
    "workable": "Workable (apply.workable.com)",
    "rss": "Generic RSS / Atom feed",
    "yc": "Y Combinator Jobs RSS",
    "brightdata_linkedin": "Bright Data — LinkedIn Jobs (paid API)",
    "brightdata_glassdoor": "Bright Data — Glassdoor Jobs (paid API)",
}

KIND_HINTS: dict[str, str] = {
    "greenhouse": "Company slug from boards.greenhouse.io/<slug>.",
    "lever": "Company slug from jobs.lever.co/<slug>.",
    "ashby": "Job-board slug from jobs.ashbyhq.com/<slug>.",
    "workable": "Account subdomain from apply.workable.com/<slug>.",
    "rss": "Full RSS / Atom feed URL (https://…).",
    "yc": "Full Y Combinator Atom feed URL (e.g. https://www.workatastartup.com/companies/feed.atom).",
    "brightdata_linkedin": (
        "Search keyword (e.g. 'senior backend engineer'). Set "
        "filters.location_include for a city / country. Requires a "
        "Bright Data API key on the Settings page."
    ),
    "brightdata_glassdoor": (
        "Search keyword (e.g. 'data scientist'). Set "
        "filters.location_include for a city / country. Requires a "
        "Bright Data API key on the Settings page."
    ),
}

# Curated known-good slugs / URLs the UI can offer as click-to-fill
# examples. The list is intentionally small — these were verified
# reachable when the feature shipped, but ATS choices change, so we
# treat the list as a starting point, not a guarantee.
KIND_EXAMPLES: dict[str, list[dict[str, str]]] = {
    "greenhouse": [
        {"label": "Airbnb", "value": "airbnb"},
        {"label": "Stripe", "value": "stripe"},
        {"label": "DoorDash", "value": "doordash"},
        {"label": "Discord", "value": "discord"},
        {"label": "Robinhood", "value": "robinhood"},
        {"label": "Anthropic", "value": "anthropic"},
        {"label": "Reddit", "value": "reddit"},
        {"label": "Coinbase", "value": "coinbase"},
        {"label": "Figma", "value": "figma"},
    ],
    "lever": [
        {"label": "Netflix", "value": "netflix"},
        {"label": "Spotify", "value": "spotify"},
        {"label": "Twitch", "value": "twitch"},
        {"label": "Brex", "value": "brex"},
        {"label": "Plaid", "value": "plaid"},
        {"label": "Mistral AI", "value": "mistral"},
        {"label": "KeepTruckin (Motive)", "value": "gomotive"},
    ],
    "ashby": [
        {"label": "Ramp", "value": "ramp"},
        {"label": "Notion", "value": "notion"},
        {"label": "Linear", "value": "Linear"},
        {"label": "Vercel", "value": "Vercel"},
        {"label": "Replit", "value": "replit"},
        {"label": "Posthog", "value": "posthog"},
    ],
    "workable": [
        {"label": "Persona", "value": "persona"},
        {"label": "Lokalise", "value": "lokalise"},
        {"label": "Pipedrive", "value": "pipedrive"},
    ],
    "rss": [
        {
            "label": "RemoteOK (all jobs)",
            "value": "https://remoteok.com/remote-jobs.rss",
        },
        {
            "label": "WeWorkRemotely (programming)",
            "value": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        },
    ],
    # YC's older /companies/feed.atom URLs returned 404 in testing; until
    # we verify a current YC feed URL, leave the chips empty so users
    # don't paste something that 404s. The `yc` kind itself still works
    # — paste any verified YC RSS / Atom URL by hand.
    "yc": [],
    "brightdata_linkedin": [
        {"label": "Senior backend engineer", "value": "senior backend engineer"},
        {"label": "Staff software engineer", "value": "staff software engineer"},
        {"label": "Data engineer", "value": "data engineer"},
        {"label": "Engineering manager", "value": "engineering manager"},
    ],
    "brightdata_glassdoor": [
        {"label": "Senior backend engineer", "value": "senior backend engineer"},
        {"label": "Product manager", "value": "product manager"},
        {"label": "Data scientist", "value": "data scientist"},
    ],
}


__all__ = [
    "ADAPTERS",
    "KIND_LABELS",
    "KIND_HINTS",
    "KIND_EXAMPLES",
    "RawLead",
    "Adapter",
]
