"""Organization CRUD + typeahead search.

Organizations are shared across users — one "MIT" entry is reusable whether the
user got a degree there, worked there, or is applying there. The UI creates
them on demand from free-form typed names (Monarch Money–style merchants).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import Contact, Education, WorkExperience
from app.models.jobs import Organization, TrackedJob
from app.models.user import User
from app.schemas.organizations import (
    ORG_TYPES,
    OrganizationIn,
    OrganizationOut,
    OrganizationSummary,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _validate_type(org_type: str) -> str:
    if org_type not in ORG_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown organization type '{org_type}'. Allowed: {sorted(ORG_TYPES)}",
        )
    return org_type


@router.get("", response_model=list[OrganizationSummary])
async def list_organizations(
    q: str | None = Query(default=None, description="Case-insensitive prefix search on name"),
    type: str | None = Query(default=None, description="Filter by type"),
    limit: int = Query(default=25, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Organization]:
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q}%"))
    if type:
        stmt = stmt.where(Organization.type == type)
    stmt = stmt.order_by(Organization.name).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{org_id}", response_model=OrganizationOut)
async def get_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Organization:
    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return obj


@router.get("/{org_id}/usage")
async def organization_usage(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Counts of how this organization is referenced, scoped to the current user."""

    async def count(stmt) -> int:
        return int((await db.execute(stmt)).scalar() or 0)

    return {
        "work_experiences": await count(
            select(func.count())
            .select_from(WorkExperience)
            .where(
                WorkExperience.user_id == user.id,
                WorkExperience.organization_id == org_id,
                WorkExperience.deleted_at.is_(None),
            )
        ),
        "educations": await count(
            select(func.count())
            .select_from(Education)
            .where(
                Education.user_id == user.id,
                Education.organization_id == org_id,
                Education.deleted_at.is_(None),
            )
        ),
        "tracked_jobs": await count(
            select(func.count())
            .select_from(TrackedJob)
            .where(
                TrackedJob.user_id == user.id,
                TrackedJob.organization_id == org_id,
                TrackedJob.deleted_at.is_(None),
            )
        ),
        "contacts": await count(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.user_id == user.id,
                Contact.organization_id == org_id,
                Contact.deleted_at.is_(None),
            )
        ),
    }


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Organization:
    _validate_type(payload.type)
    # Case-insensitive exact-name match on a non-deleted org → return it
    # instead of creating a duplicate. Keeps the combobox "create on Enter"
    # flow idempotent when the user types something that already exists.
    existing_stmt = select(Organization).where(
        func.lower(Organization.name) == payload.name.strip().lower(),
        Organization.deleted_at.is_(None),
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    obj = Organization(**payload.model_dump(exclude_unset=True))
    obj.name = obj.name.strip()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{org_id}", response_model=OrganizationOut)
async def update_organization(
    org_id: int,
    payload: OrganizationIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Organization:
    _validate_type(payload.type)
    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    from datetime import datetime, timezone

    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# --- Company researcher -----------------------------------------------------

import json as _json
import logging as _logging
import re as _re
from typing import Optional as _Optional

from pydantic import BaseModel as _BaseModel

from app.skills.runner import (
    ClaudeCodeError as _ClaudeCodeError,
    run_claude_prompt as _run_claude_prompt,
)

_log = _logging.getLogger(__name__)

_RESEARCH_PROMPT = """You are summarizing what the user already
downloaded about the company "{name}". The corpus below is verbatim
text from a small set of pages we fetched ourselves. Do NOT call
WebSearch, WebFetch, or any other tool — read the corpus and emit
one JSON object.

{hint_block}

Return ONE JSON object, no prose, no markdown fences:

{{
  "name": string,                 // canonical name (may differ from input)
  "website": string | null,
  "industry": string | null,      // one or two words
  "size": "1-10" | "11-50" | "51-200" | "201-500" | "501-1000" |
          "1001-5000" | "5001-10000" | "10000+" | null,
  "headquarters_location": string | null,
  "founded_year": number | null,
  "description": string | null,   // 2-3 sentence summary of what they do
  "research_notes": string | null, // 1-3 short paragraphs of additional context
                                  // (history, notable products, recent news,
                                  // culture signals). Markdown OK.
  "source_links": string[] | null, // actual URLs you consulted, de-duplicated
  "tech_stack_hints": string[] | null,
  "reputation_signals": {{
    "engineering_culture": string | null,
    "work_life_balance": string | null,
    "layoff_history": string | null,
    "recent_news": string | null,
    "red_flags": string[] | null,
    "green_flags": string[] | null
  }} | null,
  "warning": string | null
}}

Rules:
- Prefer null over guessing. If a field truly isn't visible in the
  corpus, null is better than a plausible-sounding fabrication.
- `size` must be a bucket, not a raw number.
- `source_links` is the URL list under "SOURCES" below — copy them
  verbatim, do not invent any.
- `research_notes` should NOT regurgitate `description` — it's the
  deeper context a candidate would actually want before interviewing.

============================================================
SOURCES
============================================================
{sources_block}

============================================================
CORPUS
============================================================
{corpus}
"""


_RESEARCH_FALLBACK_PROMPT = """We couldn't directly download anything
useful for "{name}" ({fail_reason}). Use WebSearch + WebFetch to
gather a corpus quickly — at most TWO WebSearch calls and TWO
WebFetch calls total. Then emit the same JSON schema below.

{hint_block}

Schema:
{{
  "name": string,
  "website": string | null,
  "industry": string | null,
  "size": "1-10" | "11-50" | "51-200" | "201-500" | "501-1000" |
          "1001-5000" | "5001-10000" | "10000+" | null,
  "headquarters_location": string | null,
  "founded_year": number | null,
  "description": string | null,
  "research_notes": string | null,
  "source_links": string[] | null,
  "tech_stack_hints": string[] | null,
  "reputation_signals": {{
    "engineering_culture": string | null,
    "work_life_balance": string | null,
    "layoff_history": string | null,
    "recent_news": string | null,
    "red_flags": string[] | null,
    "green_flags": string[] | null
  }} | null,
  "warning": string | null
}}
"""


class _ResearchIn(_BaseModel):
    hint: _Optional[str] = None  # optional user-provided focus area


_JSON_RE = _re.compile(r"\{[\s\S]*\}", _re.MULTILINE)


_RESEARCH_BUDGET = 50_000  # chars across all fetched pages combined.
_RESEARCH_PER_PAGE_CAP = 18_000


async def _fetch_corpus_for_org(
    name: str, website: _Optional[str]
) -> tuple[str, list[str], _Optional[str]]:
    """Pull a small corpus of text about `name` directly via httpx.
    Returns (corpus_markdown, source_urls, fail_reason).

    Strategy is pragmatic: hit (1) the org's website if we have one or
    a guessed URL, and (2) the company's Wikipedia page (if it exists).
    Two HTTP calls max, no Claude. The Claude step that follows
    summarizes whatever we found — no exploration, no recursion.
    """
    from app.sources._common import (
        UpstreamGateError,
        html_to_md,
        http_get_text,
    )
    import httpx

    candidates: list[str] = []
    if website:
        w = website.strip()
        if not w.startswith("http"):
            w = "https://" + w
        candidates.append(w)
    else:
        # Best-effort guess at the homepage from the name. Lots of
        # noise but cheap to try; the parse step happily ignores it
        # if it 404s.
        slug = "".join(c for c in name.lower() if c.isalnum())
        if slug:
            candidates.append(f"https://www.{slug}.com")
    # Wikipedia is a reliably-structured second source.
    wiki_slug = name.strip().replace(" ", "_")
    candidates.append(f"https://en.wikipedia.org/wiki/{wiki_slug}")

    pages: list[tuple[str, str]] = []
    last_fail: _Optional[str] = None
    for u in candidates:
        try:
            body = await http_get_text(u, timeout=20.0)
        except UpstreamGateError as exc:
            last_fail = f"{u}: bot-gated ({exc})"
            continue
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            last_fail = f"{u}: HTTP {code}"
            continue
        except httpx.HTTPError as exc:
            last_fail = f"{u}: {exc}"
            continue
        except Exception as exc:  # pragma: no cover  (defensive)
            last_fail = f"{u}: {type(exc).__name__}: {exc}"
            continue
        md = html_to_md(body)
        if not md or len(md.strip()) < 200:
            last_fail = f"{u}: thin response"
            continue
        if len(md) > _RESEARCH_PER_PAGE_CAP:
            md = md[:_RESEARCH_PER_PAGE_CAP] + "\n\n[… truncated …]"
        pages.append((u, md))

    if not pages:
        return "", [], last_fail or "no candidates resolved"

    chunks: list[str] = []
    sources: list[str] = []
    total = 0
    for u, md in pages:
        block = f"### Source: {u}\n\n{md}\n"
        if total + len(block) > _RESEARCH_BUDGET:
            block = block[: _RESEARCH_BUDGET - total] + "\n[… truncated …]"
        chunks.append(block)
        sources.append(u)
        total += len(block)
        if total >= _RESEARCH_BUDGET:
            break
    return "\n\n".join(chunks), sources, None


def _extract_json(text: str) -> _Optional[dict]:
    text = text.strip()
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass
    if text.startswith("```"):
        inner = "\n".join(text.splitlines()[1:])
        if inner.rstrip().endswith("```"):
            inner = inner.rsplit("```", 1)[0]
        try:
            return _json.loads(inner)
        except _json.JSONDecodeError:
            pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return _json.loads(m.group(0))
        except _json.JSONDecodeError:
            return None
    return None


async def run_org_research_pipeline(
    db: AsyncSession, obj: Organization, hint: _Optional[str] = None
) -> Organization:
    """The actual research-an-org pipeline. Used by both the HTTP
    endpoint and the queue worker's `org_research` handler. Mutates
    `obj` in place, commits, and returns it. Raises ClaudeCodeError
    on Claude failure — caller decides how to surface it."""
    hint_block = (
        f"User focus for this research pass: {hint.strip()}"
        if hint and hint.strip()
        else "No specific focus — produce a general company overview."
    )

    # Stage 1: pull a corpus directly via httpx (homepage + Wikipedia).
    # Two HTTP calls, no Claude. Then Stage 2 summarizes — no
    # exploration, no recursion.
    corpus, sources, fail_reason = await _fetch_corpus_for_org(
        obj.name, obj.website
    )
    if corpus:
        sources_block = "\n".join(f"- {u}" for u in sources)
        prompt = _RESEARCH_PROMPT.format(
            name=obj.name,
            hint_block=hint_block,
            sources_block=sources_block,
            corpus=corpus,
        )
        allowed_tools: list[str] = []
    else:
        # Stage 1 found nothing usable — fall back to Claude with a
        # tight tool budget. Caller will see this in the activity feed.
        prompt = _RESEARCH_FALLBACK_PROMPT.format(
            name=obj.name,
            hint_block=hint_block,
            fail_reason=fail_reason or "unknown",
        )
        allowed_tools = ["WebFetch", "WebSearch"]

    from app.skills.queue_bus import run_claude_to_bus

    final_text = await run_claude_to_bus(
        prompt=prompt,
        source="org_research",
        item_id=f"org:{obj.id}",
        label=f"Research: {obj.name}",
        allowed_tools=allowed_tools,
        timeout_seconds=180,
    )

    data = _extract_json(final_text) or {}
    _apply_research_to_org(obj, data)
    await db.commit()
    await db.refresh(obj)
    return obj


def _apply_research_to_org(obj: Organization, data: dict) -> None:
    """Apply a research-pipeline JSON result to an Organization row.
    Only overwrites empty fields; merges list fields; always refreshes
    research_notes + reputation_signals."""

    # Fill only if empty — don't stomp user-entered data.
    scalar_fields = [
        "website",
        "industry",
        "size",
        "headquarters_location",
        "description",
    ]
    for field in scalar_fields:
        val = data.get(field)
        if val and not getattr(obj, field, None):
            setattr(obj, field, val)

    if data.get("founded_year") and not obj.founded_year:
        try:
            obj.founded_year = int(data["founded_year"])
        except (TypeError, ValueError):
            pass

    # research_notes and reputation_signals always refresh — that's the whole
    # point of the call.
    if data.get("research_notes"):
        obj.research_notes = data["research_notes"]
    if data.get("reputation_signals") is not None:
        obj.reputation_signals = data["reputation_signals"]

    # Merge list fields.
    for field in ("source_links", "tech_stack_hints"):
        new_items = data.get(field) or []
        if not isinstance(new_items, list):
            continue
        existing = list(getattr(obj, field) or [])
        merged = existing + [x for x in new_items if x not in existing]
        if merged:
            setattr(obj, field, merged)


@router.post("/{org_id}/research", response_model=OrganizationOut)
async def research_organization(
    org_id: int,
    payload: _ResearchIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Organization:
    """Run the Companion to enrich an organization in place.

    Safe-by-default: we only OVERWRITE fields that are currently null/empty.
    Multi-valued fields (source_links, tech_stack_hints) are merged rather
    than replaced. `research_notes` always overwrites — that's the field the
    user knows they're refreshing.
    """
    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    try:
        return await run_org_research_pipeline(db, obj, payload.hint)
    except _ClaudeCodeError as exc:
        _log.warning("Org research failed for %s (%s): %s", obj.name, org_id, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")
