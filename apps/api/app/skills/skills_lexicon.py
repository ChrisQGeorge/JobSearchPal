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

# In-process cache: (built_at_monotonic, _Lexicon). The lexicon changes
# slowly (new skills trickle in per parse), so a short TTL keeps fetches
# from re-querying two tables every time.
_CACHE: Optional[tuple[float, "_Lexicon"]] = None
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

# Cue phrases that mark a PROSE sentence as stating a candidate
# requirement, for postings with informal structure (no headings, no
# bullets). Like the heading markers, this vocabulary self-heals: the
# escalation call can return new generic cues, persisted under "cues"
# in the same store.
_SEED_CUE_RE = re.compile(
    r"(experience (?:with|in|using|of)|years? of experience|proficien"
    r"|expertise|knowledge of|familiar(?:ity)? with|working knowledge"
    r"|understanding of|must (?:have|be|know)|should (?:have|be|know)"
    r"|need(?:s|ed)? to (?:have|know|be)|you.{0,3}ll need"
    r"|we.{0,3}re looking for|looking for someone|ideal candidate"
    r"|qualified candidates?|ability to|able to|capable of"
    r"|strong background|background in|track record|hands[- ]on"
    r"|skilled (?:in|at)|competenc|certif(?:ied|ication)|degree in"
    r"|you (?:have|are|bring|know)|required|requirements?|prerequisit"
    r"|a plus|bonus if|nice to have|comfortable (?:with|using))",
    re.IGNORECASE,
)

# Sentence/clause boundaries for prose segmentation.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\s*;\s+")

# (loaded_monotonic, {"required": re|None, "nice": re|None, "other": re|None})
_MARKER_CACHE: Optional[tuple[float, dict[str, Optional[re.Pattern]]]] = None


def _load_marker_store() -> dict[str, list[str]]:
    try:
        raw = json.loads(_MARKERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    out: dict[str, list[str]] = {}
    for kind in ("required", "nice", "other", "cues"):
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
    cues: list[str] | None = None,
    seen_in: list[str] | None = None,
) -> int:
    """Persist new section-heading marker phrases and requirement-cue
    phrases. Each phrase must actually occur in one of the `seen_in`
    lines (case-insensitive) — a model can only teach markers it was
    shown, never invent them. Returns how many phrases were newly
    added."""
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
        ("required", required), ("nice", nice), ("other", other),
        ("cues", cues),
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
    """Regex for terms the token matcher can't represent (".NET", "R&D")."""
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


# --- Token matcher -----------------------------------------------------------
#
# One regex per lexicon term (thousands) scanned across every description
# was CPU-bound on the event loop — a bulk "Add to tracker" of Bright Data
# leads ran it back to back in every queue slot and starved the API. The
# lexicon is now a dict of normalized word sequences: tokenize the text
# once and look up every 1..N-word window — O(tokens), not O(terms × text).
#
# Two token streams give the old whole-word semantics:
#   compound tokens keep internal . / ' - joins: "node.js", "ci/cd", "c++"
#   atomic tokens split those: "c++/java" -> "c++", "java"
# so "Java" still matches inside "C++/Java" and "Sr" never matches
# "Srinivas". Terms that don't survive tokenization unchanged (".NET",
# "R&D") fall back to a regex — there are few of them.

_COMPOUND_TOKEN = re.compile(r"[a-z0-9+#]+(?:[./'\-][a-z0-9+#]+)*")
_ATOMIC_TOKEN = re.compile(r"[a-z0-9+#]+")
_MAX_TERM_WORDS = 6


class _Lexicon:
    def __init__(self) -> None:
        self.terms: dict[str, str] = {}   # "machine learning" -> "Machine Learning"
        self.odd: list[tuple[re.Pattern, str]] = []
        self.max_n = 1

    def add(self, display: str) -> None:
        t = display.strip()
        low = re.sub(r"\s+", " ", t.lower())
        if len(t) < 2 or len(t) > 64 or low in _STOPWORDS:
            return
        toks = _COMPOUND_TOKEN.findall(low)
        key = " ".join(toks)
        if toks and key == low and len(toks) <= _MAX_TERM_WORDS:
            self.terms.setdefault(key, t)
            self.max_n = max(self.max_n, len(toks))
        else:
            pat = _compile_term(t)
            if pat is not None:
                self.odd.append((pat, t))

    def __len__(self) -> int:
        return len(self.terms) + len(self.odd)

    def _streams(self, low: str):
        for rx in (_COMPOUND_TOKEN, _ATOMIC_TOKEN):
            yield [(m.group(0), m.start()) for m in rx.finditer(low)]

    def find(self, text: str) -> dict[str, int]:
        """{display term: first character offset} for every term present."""
        low = text.lower()
        hits: dict[str, int] = {}
        for toks in self._streams(low):
            words = [w for w, _ in toks]
            for i in range(len(words)):
                for n in range(1, min(self.max_n, len(words) - i) + 1):
                    disp = self.terms.get(" ".join(words[i:i + n]))
                    if disp is not None and (disp not in hits or toks[i][1] < hits[disp]):
                        hits[disp] = toks[i][1]
        for pat, disp in self.odd:
            m = pat.search(text)
            if m and (disp not in hits or m.start() < hits[disp]):
                hits[disp] = m.start()
        return hits

    def any_hit(self, text: str) -> bool:
        low = text.lower()
        for toks in self._streams(low):
            words = [w for w, _ in toks]
            for i in range(len(words)):
                for n in range(1, min(self.max_n, len(words) - i) + 1):
                    if " ".join(words[i:i + n]) in self.terms:
                        return True
        return any(pat.search(text) for pat, _ in self.odd)


def make_lexicon(terms) -> _Lexicon:
    lex = _Lexicon()
    for t in terms:
        lex.add(str(t))
    return lex


async def _build_lexicon() -> _Lexicon:
    from sqlalchemy import select

    from app.core.database import BgSessionLocal as SessionLocal
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

    out = make_lexicon(display_by_norm.values())
    log.debug(
        "Skills lexicon built: %d token terms, %d regex terms",
        len(out.terms), len(out.odd),
    )
    return out


async def get_lexicon() -> _Lexicon:
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


def _segment_text(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Split a JD into (content, context) segments regardless of
    formatting: bullets become one segment each, prose is split into
    sentences/clauses. Context is the classification of the nearest
    heading above ('req' / 'other' / 'unknown') or 'none' when the text
    has no headings at all — structure is a hint, never a requirement.
    Also returns unknown_headings: heading-ish lines with meaningful
    content beneath (≥2 bullets or ≥150 chars of prose) that matched no
    known section marker."""
    segments: list[tuple[str, str]] = []
    unknown_headings: list[str] = []
    context = "none"
    pending_unknown: Optional[str] = None
    pending_weight = 0  # bullets count 100 each; prose counts its chars
    prose_buf: list[str] = []

    def _flush_prose() -> None:
        nonlocal prose_buf
        if not prose_buf:
            return
        block = " ".join(prose_buf)
        prose_buf = []
        for sent in _SENT_SPLIT_RE.split(block):
            s = sent.strip()
            if len(s) >= 25:
                segments.append((s[:250], context))

    def _flush_unknown() -> None:
        nonlocal pending_unknown, pending_weight
        if (
            pending_unknown
            and pending_weight >= 150
            and len(unknown_headings) < 8
        ):
            unknown_headings.append(pending_unknown)
        pending_unknown = None
        pending_weight = 0

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            _flush_prose()
            continue
        if _HEADING_LINE_RE.match(line):
            _flush_prose()
            _flush_unknown()
            context = _heading_kind(stripped)
            if context == "unknown":
                pending_unknown = stripped.lstrip("#* ").rstrip("* ")[:100]
            continue
        m = _BULLET_RE.match(line)
        if m:
            _flush_prose()
            segments.append((m.group(1).strip()[:250], context))
            if pending_unknown:
                pending_weight += 100
            continue
        prose_buf.append(stripped)
        if pending_unknown:
            pending_weight += len(stripped)
    _flush_prose()
    _flush_unknown()
    return segments, unknown_headings


async def assess_requirements_coverage(text: str) -> dict:
    """Coverage report over the JD's requirement statements — bullets
    OR prose, formal structure not required. A segment enters the
    denominator when it sits under a requirements-style heading, or
    (with no heading context) when it matches a requirement cue phrase
    ("experience with", "must have", …). Segments under recognized
    non-requirements sections (benefits, company blurb) never enter.

    Returns {total, covered, coverage (0-1), uncovered_lines,
    unknown_headings, candidate_lines}. total == 0 means nothing
    recognizable to gate on. unknown_headings are headings the marker
    vocabulary couldn't classify. candidate_lines is a capped sample of
    all non-fluff segments — the escalation payload for the
    zero-skills-found case, where coverage math alone can't be
    trusted."""
    empty = {
        "total": 0,
        "covered": 0,
        "coverage": 1.0,
        "uncovered_lines": [],
        "unknown_headings": [],
        "candidate_lines": [],
    }
    if not text or not text.strip():
        return empty
    lexicon = await get_lexicon()
    learned_cues = _learned_res()["cues"]

    def _cue(content: str) -> bool:
        if _SEED_CUE_RE.search(content):
            return True
        return learned_cues is not None and learned_cues.search(content) is not None

    segments, unknown_headings = _segment_text(text)
    total = 0
    covered = 0
    uncovered: list[str] = []
    candidates: list[str] = []
    for content, ctx in segments:
        if ctx == "other":
            continue
        if len(candidates) < 10:
            candidates.append(content[:200])
        if ctx != "req" and not _cue(content):
            continue
        total += 1
        hit = _NONSKILL_REQ_RE.search(content) is not None or lexicon.any_hit(content)
        if hit:
            covered += 1
        elif len(uncovered) < 10:
            uncovered.append(content[:200])
    if total == 0:
        return {
            **empty,
            "unknown_headings": unknown_headings,
            "candidate_lines": candidates,
        }
    return {
        "total": total,
        "covered": covered,
        "coverage": covered / total,
        "uncovered_lines": uncovered,
        "unknown_headings": unknown_headings,
        "candidate_lines": candidates,
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
    # In order of first appearance in the posting.
    for display, pos in sorted(lexicon.find(text).items(), key=lambda kv: kv[1]):
        if nice_start is not None and pos >= nice_start:
            if len(nice) < 20:
                nice.append(display)
        elif len(required) < 30:
            required.append(display)
    return required, nice
