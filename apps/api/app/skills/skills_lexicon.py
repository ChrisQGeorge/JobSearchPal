"""Deterministic skill extraction backed by a lexicon that grows over time.

The lexicon is derived, not curated: it's the union of

  1. the user's Skill catalog (names + aliases), and
  2. every skill string ever extracted onto a TrackedJob
     (required_skills / nice_to_have_skills) by ANY past parse — LLM,
     JSON-LD, or generated extractor.

Because each LLM fallback parse persists its extracted skills onto the
job row, every fallback teaches the lexicon new vocabulary, and the
deterministic keyword matcher gets better with use — no separate
training store to maintain.

Matching is exact-term, word-boundary, case-insensitive; terms with
non-word characters (C++, C#, Node.js) use lookaround boundaries so
they still match. Required vs nice-to-have is decided by section: terms
first appearing after a "nice to have / preferred / bonus" heading are
classified nice-to-have.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# In-process cache: (built_at_monotonic, [(compiled_pattern, display_name)]).
# The lexicon changes slowly (new skills trickle in per parse), so a short
# TTL keeps fetches from re-querying two tables every time.
_CACHE: Optional[tuple[float, list[tuple[re.Pattern, str]]]] = None
_CACHE_TTL_SECONDS = 300

# Terms that are technically in catalogs but match half of English.
_STOPWORDS = {
    "it", "go", "r", "c", "api", "web", "design", "support", "management",
    "communication", "teamwork", "leadership", "testing", "research",
}

_MAX_TERMS = 5000

# --- Section-heading markers (self-healing) --------------------------------
#
# Which headings open a requirements / nice-to-have section is itself
# learned vocabulary, not a fixed regex: the seeds below are merged with
# marker phrases stored on the claude_config volume (git-proof, same
# home as the generated extractors). When the coverage pass sees a
# heading-ish line with bullets under it that matches NO known marker,
# it reports it as an "unknown heading"; the escalation model call
# classifies it and `learn_heading_markers` persists the generic phrase
# ("must haves", "what we're looking for", …) — including "other"
# markers (benefits, responsibilities, …) so a heading classified as
# not-requirements is remembered too and never re-triggers a call.

_MARKERS_PATH = Path("/root/.claude/jsp-extractors/heading_markers.json")
_MARKERS_MAX_PER_KIND = 150

_SEED_REQ_RE = re.compile(
    r"(requirements?|qualifications?|what you.{0,3}ll need|must[- ]haves?"
    r"|skills? (?:&|and) experience|required skills?|about you|who you are"
    r"|nice[\s-]*to[\s-]*have|preferred qualifications?)",
    re.IGNORECASE,
)

_SEED_NICE_RE = re.compile(
    r"(nice[\s-]*to[\s-]*have|preferred qualifications|preferred skills"
    r"|bonus points|bonus:|a plus|plusses|great if|good to have"
    r"|not required but)",
    re.IGNORECASE,
)

_SEED_OTHER_RE = re.compile(
    r"(benefits|perks|compensation|what we offer|we offer|why join"
    r"|about (?:us|the (?:company|team|role|job))|the role|your mission"
    r"|responsibilit|duties|what you.{0,3}ll (?:do|be doing)|day[- ]to[- ]day"
    r"|our (?:values|culture|mission|stack|story)|who we are|how to apply"
    r"|application process|interview process|hiring process|equal opportunit"
    r"|next steps|salary|location|schedule|working hours)",
    re.IGNORECASE,
)

# (loaded_monotonic, {"required": re|None, "nice": re|None, "other": re|None})
_MARKER_CACHE: Optional[tuple[float, dict[str, Optional[re.Pattern]]]] = None


def _load_marker_store() -> dict[str, list[str]]:
    try:
        raw = json.loads(_MARKERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    out: dict[str, list[str]] = {}
    for kind in ("required", "nice", "other"):
        vals = raw.get(kind) if isinstance(raw, dict) else None
        out[kind] = [
            str(v) for v in vals if str(v).strip()
        ][: _MARKERS_MAX_PER_KIND] if isinstance(vals, list) else []
    return out


def _learned_res() -> dict[str, Optional[re.Pattern]]:
    global _MARKER_CACHE
    now = time.monotonic()
    if _MARKER_CACHE is not None and now - _MARKER_CACHE[0] < _CACHE_TTL_SECONDS:
        return _MARKER_CACHE[1]
    store = _load_marker_store()
    res: dict[str, Optional[re.Pattern]] = {}
    for kind, phrases in store.items():
        parts = [re.escape(p) for p in phrases if len(p) >= 3]
        res[kind] = (
            re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)
            if parts
            else None
        )
    _MARKER_CACHE = (now, res)
    return res


def _heading_kind(stripped_line: str) -> str:
    """Classify a heading-ish line: 'req' opens a requirements-style
    section (nice-to-have counts — its bullets are requirements-section
    content for coverage purposes), 'other' is a recognized
    non-requirements section, 'unknown' matches no known marker."""
    learned = _learned_res()
    if _SEED_REQ_RE.search(stripped_line):
        return "req"
    for kind in ("required", "nice"):
        pat = learned[kind]
        if pat is not None and pat.search(stripped_line):
            return "req"
    if _SEED_OTHER_RE.search(stripped_line):
        return "other"
    pat = learned["other"]
    if pat is not None and pat.search(stripped_line):
        return "other"
    return "unknown"


def _nice_start(text: str) -> Optional[int]:
    """Offset of the first nice-to-have-style heading marker, if any."""
    positions = []
    m = _SEED_NICE_RE.search(text)
    if m:
        positions.append(m.start())
    pat = _learned_res()["nice"]
    if pat is not None:
        m = pat.search(text)
        if m:
            positions.append(m.start())
    return min(positions) if positions else None


def _normalize_marker(phrase: str) -> str:
    p = re.sub(r"[#*_`]+", " ", str(phrase or ""))
    p = re.sub(r"\s+", " ", p).strip().strip(":").strip().lower()
    return p


def learn_heading_markers(
    *,
    required: list[str] | None = None,
    nice: list[str] | None = None,
    other: list[str] | None = None,
    seen_in: list[str] | None = None,
) -> int:
    """Persist new section-heading marker phrases. Each phrase must
    actually occur in one of the `seen_in` heading lines (case-
    insensitive) — a model can only teach markers it was shown, never
    invent them. Returns how many phrases were newly added."""
    global _MARKER_CACHE
    haystack = "\n".join(seen_in or []).lower()
    store = _load_marker_store()
    known = {
        _normalize_marker(p)
        for phrases in store.values()
        for p in phrases
    }
    added = 0
    for kind, phrases in (
        ("required", required), ("nice", nice), ("other", other)
    ):
        for raw in phrases or []:
            p = _normalize_marker(raw)
            if not (3 <= len(p) <= 48) or p in known:
                continue
            if haystack and p not in haystack:
                continue
            if len(store[kind]) >= _MARKERS_MAX_PER_KIND:
                continue
            store[kind].append(p)
            known.add(p)
            added += 1
    if added:
        try:
            _MARKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _MARKERS_PATH.write_text(
                json.dumps(store, indent=2), encoding="utf-8"
            )
            _MARKER_CACHE = None
            log.info("Learned %d heading marker(s)", added)
        except Exception as exc:
            log.warning("Could not persist heading markers: %s", exc)
            return 0
    return added


def _compile_term(term: str) -> Optional[re.Pattern]:
    t = term.strip()
    if len(t) < 2 or len(t) > 64:
        return None
    if t.lower() in _STOPWORDS:
        return None
    escaped = re.escape(t)
    if re.fullmatch(r"[\w\s-]+", t):
        pat = rf"\b{escaped}\b"
    else:
        # C++, C#, Node.js, .NET … word boundaries don't work around
        # symbols; use explicit non-alphanumeric lookarounds instead.
        pat = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
    try:
        return re.compile(pat, re.IGNORECASE)
    except re.error:
        return None


async def _build_lexicon() -> list[tuple[re.Pattern, str]]:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.history import Skill
    from app.models.jobs import TrackedJob

    display_by_norm: dict[str, str] = {}

    def _add(raw: object) -> None:
        s = str(raw or "").strip()
        norm = s.lower()
        if s and norm not in display_by_norm and len(display_by_norm) < _MAX_TERMS:
            display_by_norm[norm] = s

    async with SessionLocal() as db:
        for name, aliases in (
            await db.execute(
                select(Skill.name, Skill.aliases).where(Skill.deleted_at.is_(None))
            )
        ).all():
            _add(name)
            if isinstance(aliases, list):
                for a in aliases:
                    _add(a)
        for req, nice in (
            await db.execute(
                select(
                    TrackedJob.required_skills, TrackedJob.nice_to_have_skills
                ).where(TrackedJob.deleted_at.is_(None))
            )
        ).all():
            for lst in (req, nice):
                if isinstance(lst, list):
                    for s in lst:
                        _add(s)

    out: list[tuple[re.Pattern, str]] = []
    for norm, display in display_by_norm.items():
        pat = _compile_term(display)
        if pat is not None:
            out.append((pat, display))
    log.debug("Skills lexicon built: %d terms", len(out))
    return out


async def get_lexicon() -> list[tuple[re.Pattern, str]]:
    global _CACHE
    now = time.monotonic()
    if _CACHE is not None and now - _CACHE[0] < _CACHE_TTL_SECONDS:
        return _CACHE[1]
    lex = await _build_lexicon()
    _CACHE = (now, lex)
    return lex


# --- Requirements coverage ("code coverage, but for the JD") ---------------
#
# After the lexicon pass, we measure how much of the posting's
# REQUIREMENTS section was actually accounted for. A bullet line counts
# as covered when (a) a lexicon term matched it, or (b) it matches a
# non-skill pattern — content that's either captured by other structured
# fields (years of experience, degree, work authorization) or genuinely
# not a skill (soft-skill / culture boilerplate). Prose outside
# requirement sections (company fluff, benefits blurbs) never enters the
# denominator, so an LLM never needs to look at it. Low coverage means
# the lexicon is missing vocabulary for this posting — the caller sends
# ONLY the uncovered lines to a model, and the extracted terms persist
# onto the job, which feeds them back into the lexicon for next time.

# A "heading-ish" line: markdown heading, or a short line ending with ":".
_HEADING_LINE_RE = re.compile(r"^\s{0,3}(#{1,6}\s+\S|.{0,60}:\s*$|\*\*[^*]+\*\*\s*$)")

_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)])\s+(\S.*)$")

_NONSKILL_REQ_RE = re.compile(
    r"(\byears?\b.{0,30}\bexperience\b|\bexperience\b.{0,30}\byears?\b"
    r"|bachelor|master'?s|\bphd\b|\bdegree\b|\bdiploma\b"
    r"|authoriz|\bvisa\b|citizen|sponsorship|clearance"
    r"|communicat|collaborat|team player|interpersonal|self[- ]starter"
    r"|fast[- ]paced|detail[- ]oriented|problem[- ]solv|passion|motivated"
    r"|work ethic|organizational skills|time management|willing to learn"
    r"|equal opportunity|salary|benefits|\btravel\b|on[- ]call)",
    re.IGNORECASE,
)


async def assess_requirements_coverage(text: str) -> dict:
    """Coverage report over the JD's requirement bullets. Returns
    {total, covered, coverage (0-1), uncovered_lines,
    unknown_headings}. total == 0 means no recognizable requirements
    section — nothing to gate on. unknown_headings are heading-ish
    lines with ≥2 bullets beneath them that matched NO known section
    marker (requirements, nice-to-have, or other): candidates for the
    model to classify so the marker vocabulary heals itself."""
    empty = {
        "total": 0,
        "covered": 0,
        "coverage": 1.0,
        "uncovered_lines": [],
        "unknown_headings": [],
    }
    if not text or not text.strip():
        return empty
    lexicon = await get_lexicon()

    in_req = False
    total = 0
    covered = 0
    uncovered: list[str] = []
    unknown_headings: list[str] = []
    pending_unknown: Optional[str] = None
    pending_bullets = 0

    def _flush_unknown() -> None:
        nonlocal pending_unknown, pending_bullets
        if (
            pending_unknown
            and pending_bullets >= 2
            and len(unknown_headings) < 8
        ):
            unknown_headings.append(pending_unknown)
        pending_unknown = None
        pending_bullets = 0

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING_LINE_RE.match(line):
            _flush_unknown()
            kind = _heading_kind(stripped)
            in_req = kind == "req"
            if kind == "unknown":
                pending_unknown = stripped.lstrip("#* ").rstrip("* ")[:100]
            continue
        if not in_req:
            if pending_unknown and _BULLET_RE.match(line):
                pending_bullets += 1
            continue
        m = _BULLET_RE.match(line)
        if not m:
            continue
        content = m.group(1).strip()
        total += 1
        hit = _NONSKILL_REQ_RE.search(content) is not None or any(
            pat.search(content) for pat, _ in lexicon
        )
        if hit:
            covered += 1
        elif len(uncovered) < 10:
            uncovered.append(content[:200])
    _flush_unknown()
    if total == 0:
        return {**empty, "unknown_headings": unknown_headings}
    return {
        "total": total,
        "covered": covered,
        "coverage": covered / total,
        "uncovered_lines": uncovered,
        "unknown_headings": unknown_headings,
    }


async def extract_skills_from_text(
    text: str,
) -> tuple[list[str], list[str]]:
    """Scan `text` (a job description) against the lexicon. Returns
    (required_skills, nice_to_have_skills). Terms whose FIRST occurrence
    falls after a nice-to-have-style heading are classified
    nice-to-have; everything else is required."""
    if not text or not text.strip():
        return [], []
    lexicon = await get_lexicon()
    nice_start = _nice_start(text)

    required: list[str] = []
    nice: list[str] = []
    for pat, display in lexicon:
        hit = pat.search(text)
        if hit is None:
            continue
        if nice_start is not None and hit.start() >= nice_start:
            if len(nice) < 20:
                nice.append(display)
        else:
            if len(required) < 30:
                required.append(display)
    return required, nice
