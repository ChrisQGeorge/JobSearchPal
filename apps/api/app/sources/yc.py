"""Y Combinator jobs RSS adapter.

YC's Work-at-a-Startup site exposes Atom feeds for filtered searches
(e.g. https://www.workatastartup.com/companies/feed.atom?role=engineering).
Same parsing as the generic RSS adapter — this kind exists separately so
the UI can label it specifically and show a tailored hint."""
from __future__ import annotations

from typing import Any

from app.sources import rss_feed


async def fetch(slug_or_url: str) -> list[dict[str, Any]]:
    return await rss_feed.fetch(slug_or_url)
