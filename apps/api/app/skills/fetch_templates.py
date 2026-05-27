"""Per-host HTML fragment extractors for known job boards / ATSes.

The fetcher (`_direct_fetch_page` in api/v1/jobs.py) downloads the whole
page and hands it to Claude for parsing. Most of the time the actual job
posting is a small region inside a much larger page — nav, footer,
related-jobs widgets, cookie banners, app shell, etc. — and all that
boilerplate burns tokens at parse time.

When the URL's host matches a known template, we slice the page down
to just the job-relevant subtree before passing it to html_to_md.
That typically cuts the prompt 5–20× without losing any signal the
parser needs.

Templates are conservative — any match miss falls back to the whole
page so we never accidentally drop information. Add new sites by
appending an entry to `_TEMPLATES`.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Each template: list of CSS selectors to try in order. The first one
# that yields a non-trivial fragment wins. "Non-trivial" = at least 200
# chars of text content so we don't over-trim a page where the selector
# matches an empty stub.
_TEMPLATES: dict[str, tuple[str, ...]] = {
    # Greenhouse-hosted job boards. Two common shapes (legacy + 2024
    # redesign); we try both.
    "boards.greenhouse.io": (
        "#main",
        "#content",
        "section.job",
        "div#app_body",
    ),
    "job-boards.greenhouse.io": (
        "#main",
        "#content",
        "section.job",
    ),
    # Lever
    "jobs.lever.co": (
        ".content",
        ".posting",
        "div.section-wrapper",
    ),
    # Ashby
    "jobs.ashbyhq.com": (
        ".ashby-job-posting-right-pane",
        "main",
        "[class*='job-posting']",
    ),
    "ashbyhq.com": (
        ".ashby-job-posting-right-pane",
        "main",
    ),
    # Workday — every customer has a different subdomain but the post
    # markup is consistent.
    "myworkdayjobs.com": (
        "[data-automation-id='jobPostingDescription']",
        "[data-automation-id='jobPostingPage']",
        "main",
    ),
    # Workable
    "apply.workable.com": (
        "section.job",
        "main",
    ),
    # Bamboo HR
    "bamboohr.com": (
        "#job-section",
        "main",
    ),
    # SmartRecruiters
    "jobs.smartrecruiters.com": (
        ".job-content",
        "main",
    ),
    # JazzHR
    "applytojob.com": (
        "#app",
        ".job-detail",
        "main",
    ),
    # LinkedIn job postings (when accessible without auth)
    "linkedin.com": (
        ".description__text",
        ".jobs-description-content",
        "[class*='show-more-less-html']",
    ),
    # Indeed
    "indeed.com": (
        "#jobDescriptionText",
        ".jobsearch-jobDescriptionText",
        "[id='jobDescriptionText']",
    ),
    # Wellfound / AngelList
    "wellfound.com": (
        "[class*='job-description']",
        "main",
    ),
    # Notion-hosted job postings (some startups use this)
    "notion.site": (
        ".notion-page-content",
        "[class*='notion-page-content']",
    ),
    # Personio
    "personio.de": (
        "section.job-detail",
        "main",
    ),
    # Recruitee
    "recruitee.com": (
        ".c-job-detail__description",
        "main",
    ),
}

# Selectors to scrub on every page regardless of template — nav, footer,
# scripts, share widgets. Removing these before extraction shrinks the
# fragment further without changing what the parser sees.
_GLOBAL_STRIP_SELECTORS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
    "[aria-label*='cookie' i]",
    "[class*='cookie' i]",
    "[class*='share' i]",
    "[class*='social' i]",
    "[class*='related-jobs' i]",
    "[class*='similar-jobs' i]",
)

_MIN_USEFUL_CHARS = 200


def _match_template(host: str) -> tuple[str, ...] | None:
    """Find the template whose hostname is the longest suffix match of
    `host`. Lets a generic 'linkedin.com' rule cover 'www.linkedin.com'
    and 'jobs.linkedin.com' alike."""
    host = host.lower().strip()
    best: tuple[str, ...] | None = None
    best_len = -1
    for key, selectors in _TEMPLATES.items():
        if host == key or host.endswith("." + key):
            if len(key) > best_len:
                best = selectors
                best_len = len(key)
    return best


def extract_relevant_html(url: str, html: str) -> str:
    """Return a sliced HTML fragment if the URL's host has a template;
    otherwise return the input unchanged. Always strips obvious chrome
    selectors (nav/footer/scripts/cookie banners) — that pass is safe
    on any page.
    """
    if not html or not url:
        return html
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if not host:
        return html

    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        # bs4 should be installed (see requirements.txt) but fall through
        # gracefully if not so the fetch still works.
        log.warning("BeautifulSoup missing; skipping fetch templates")
        return html

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return html

    # 1. Global chrome strip (safe on every page).
    for sel in _GLOBAL_STRIP_SELECTORS:
        for node in soup.select(sel):
            node.decompose()

    # 2. Template-specific narrowing.
    selectors = _match_template(host)
    fragment_html: Optional[str] = None
    if selectors:
        for sel in selectors:
            try:
                node = soup.select_one(sel)
            except Exception:
                node = None
            if node is None:
                continue
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if len(text) >= _MIN_USEFUL_CHARS:
                fragment_html = str(node)
                break

    if fragment_html:
        return fragment_html

    # 3. Fallback to the chrome-stripped whole-page HTML — still smaller
    # than the original and the parser sees less noise.
    return str(soup)
