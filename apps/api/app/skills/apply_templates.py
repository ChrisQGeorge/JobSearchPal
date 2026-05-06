"""ATS-specific apply-flow templates (R11).

Each template is a coroutine that takes a Playwright page already
navigated to the JD URL and tries to advance the user through the
standard fields the ATS exposes. Returns a dict of `{field: status}`
so the caller can log what was filled vs. skipped.

Templates are best-effort. They only handle *deterministic* fields
(name, email, phone, links, resume upload). Custom questions, EEO
forms, and anything novel falls through to the generic agent loop.

Wired in `app/skills/apply_run.py`:

    if ats == "greenhouse":
        await fill_greenhouse_known_fields(page, profile, ...)
    # Generic agent loop runs after, picks up wherever the
    # template left off.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


# Field-mapping from our ResumeProfile / WorkAuthorization / Demographics
# blocks to the most common Greenhouse selectors. Each entry tries the
# selectors in order; first one that resolves wins.
GREENHOUSE_FIELD_MAP: list[tuple[str, list[str], str]] = [
    # (profile_key, [selectors], action: "fill" | "click_label")
    ("first_name", ["#first_name", "input[name='first_name']"], "fill"),
    ("last_name", ["#last_name", "input[name='last_name']"], "fill"),
    ("email", ["#email", "input[name='email']"], "fill"),
    ("phone", ["#phone", "input[name='phone']"], "fill"),
    (
        "location",
        ["#candidate-location", "#candidate_location", "input[name*='location']"],
        "fill",
    ),
    (
        "linkedin_url",
        [
            "input[name='urls[LinkedIn URL]']",
            "input[id*='linkedin' i]",
            "input[aria-label*='LinkedIn' i]",
        ],
        "fill",
    ),
    (
        "github_url",
        [
            "input[name='urls[GitHub URL]']",
            "input[id*='github' i]",
            "input[aria-label*='GitHub' i]",
        ],
        "fill",
    ),
    (
        "portfolio_url",
        [
            "input[name='urls[Website]']",
            "input[name='urls[Portfolio]']",
            "input[id*='portfolio' i]",
            "input[id*='website' i]",
        ],
        "fill",
    ),
]


def _profile_lookup(profile: dict[str, Any], key: str) -> Optional[str]:
    """Pull a single value out of a profile dict assembled by
    `_load_user_profile_block`'s structured form. Falls back to None
    if missing / blank."""
    val = profile.get(key)
    if val in (None, "", []):
        return None
    return str(val)


async def fill_greenhouse_known_fields(
    page,
    profile: dict[str, Any],
    *,
    log_fn,
) -> dict[str, str]:
    """Fill the deterministic Greenhouse fields. Returns
    `{field: "filled" | "skipped" | "error: <msg>"}`.

    `log_fn(kind, payload)` is the per-step logger from apply_run.py
    so the activity feed shows each fill.
    """
    out: dict[str, str] = {}

    # Greenhouse renders some applications behind an "Apply" button on
    # the JD page itself. Click it if present so the form appears.
    apply_btn_selectors = [
        "#apply_button",
        "a#apply_button",
        "button#apply_button",
        "a:has-text('Apply')",
        "button:has-text('Apply for this Job')",
    ]
    for sel in apply_btn_selectors:
        try:
            handle = await page.query_selector(sel)
            if handle is not None:
                await handle.click(timeout=5_000)
                await log_fn("click", {"selector": sel, "label": "greenhouse Apply"})
                await page.wait_for_load_state("networkidle", timeout=10_000)
                break
        except Exception:
            continue

    for key, selectors, action in GREENHOUSE_FIELD_MAP:
        value = _profile_lookup(profile, key)
        if not value:
            out[key] = "skipped: no profile value"
            continue
        filled = False
        for sel in selectors:
            try:
                handle = await page.query_selector(sel)
                if handle is None:
                    continue
                if action == "fill":
                    await handle.fill(value, timeout=5_000)
                else:
                    await handle.click(timeout=5_000)
                await log_fn("type", {"selector": sel, "field": key,
                                       "value_preview": value[:80]})
                filled = True
                break
            except Exception as exc:
                out[key] = f"error: {exc}"
                continue
        if filled:
            out[key] = "filled"
        elif key not in out:
            out[key] = "skipped: selector not found"

    return out


LEVER_FIELD_MAP: list[tuple[str, list[str], str]] = [
    ("full_name", ["input[name='name']", "#name"], "fill"),
    ("email", ["input[name='email']", "#email"], "fill"),
    ("phone", ["input[name='phone']", "#phone"], "fill"),
    (
        "linkedin_url",
        [
            "input[name='urls[LinkedIn]']",
            "input[name='urls[LinkedIn URL]']",
            "input[id*='linkedin' i]",
        ],
        "fill",
    ),
    (
        "github_url",
        ["input[name='urls[GitHub]']", "input[id*='github' i]"],
        "fill",
    ),
    (
        "portfolio_url",
        ["input[name='urls[Portfolio]']", "input[name='urls[Other]']"],
        "fill",
    ),
]

ASHBY_FIELD_MAP: list[tuple[str, list[str], str]] = [
    # Ashby uses generated IDs but reliably names fields by role.
    ("full_name", [
        "input[aria-label*='Full Name' i]",
        "input[name*='name' i]:not([name*='last'])",
    ], "fill"),
    ("email", ["input[aria-label*='Email' i]", "input[type='email']"], "fill"),
    ("phone", ["input[aria-label*='Phone' i]", "input[type='tel']"], "fill"),
    (
        "linkedin_url",
        ["input[aria-label*='LinkedIn' i]", "input[id*='linkedin' i]"],
        "fill",
    ),
]


async def _fill_with_map(
    page,
    profile: dict[str, Any],
    field_map: list[tuple[str, list[str], str]],
    *,
    log_fn,
) -> dict[str, str]:
    """Generic field-fill driver shared by lever / ashby. Same shape
    as the Greenhouse-specific path; just data-driven."""
    out: dict[str, str] = {}
    for key, selectors, action in field_map:
        value = _profile_lookup(profile, key)
        if not value:
            out[key] = "skipped: no profile value"
            continue
        filled = False
        for sel in selectors:
            try:
                handle = await page.query_selector(sel)
                if handle is None:
                    continue
                if action == "fill":
                    await handle.fill(value, timeout=5_000)
                else:
                    await handle.click(timeout=5_000)
                await log_fn("type", {"selector": sel, "field": key,
                                       "value_preview": value[:80]})
                filled = True
                break
            except Exception as exc:
                out[key] = f"error: {exc}"
                continue
        if filled:
            out[key] = "filled"
        elif key not in out:
            out[key] = "skipped: selector not found"
    return out


async def fill_lever_known_fields(page, profile: dict[str, Any], *, log_fn) -> dict[str, str]:
    """Lever-specific deterministic field-fill. Lever apply pages
    typically don't have a separate "Apply" click — the form is
    inline."""
    return await _fill_with_map(page, profile, LEVER_FIELD_MAP, log_fn=log_fn)


async def fill_ashby_known_fields(page, profile: dict[str, Any], *, log_fn) -> dict[str, str]:
    """Ashby-specific field-fill. Ashby uses React-rendered forms with
    aria-labels that are more reliable than generated DOM ids."""
    return await _fill_with_map(page, profile, ASHBY_FIELD_MAP, log_fn=log_fn)


def parse_profile_block(block: str) -> dict[str, Any]:
    """Parse the human-readable block emitted by `_load_user_profile_block`
    back into a flat `{field: value}` dict. Lines look like
    `- field_name: value`; we ignore section headers and continuation
    lines."""
    out: dict[str, Any] = {}
    for line in block.splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        rest = s[2:]
        if ":" not in rest:
            continue
        k, _, v = rest.partition(":")
        out[k.strip()] = v.strip()
    return out
