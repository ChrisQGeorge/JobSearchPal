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
    limit: int = Query(default=25, ge=1, le=200),
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

_RESEARCH_PROMPT = """Research the company "{name}" using WebSearch and WebFetch.
Prefer the company's own site (About, Careers, Engineering blog, Press) and
credible external sources (the company's Wikipedia page, LinkedIn company
page, Crunchbase summary, tech-press articles). Avoid Glassdoor-style rumor
aggregation unless the signal is repeated across sources.

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
- Prefer null over guessing. If a field truly isn't visible, null is better
  than a plausible-sounding fabrication.
- `size` must be a bucket, not a raw number.
- `source_links` should be ~3-6 URLs you actually fetched, not random matches.
- `research_notes` should NOT regurgitate `description` — it's the deeper
  context a candidate would actually want before interviewing.
"""


class _ResearchIn(_BaseModel):
    hint: _Optional[str] = None  # optional user-provided focus area


_JSON_RE = _re.compile(r"\{[\s\S]*\}", _re.MULTILINE)


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

    hint_block = (
        f"User focus for this research pass: {payload.hint.strip()}"
        if payload.hint and payload.hint.strip()
        else "No specific focus — produce a general company overview."
    )
    prompt = _RESEARCH_PROMPT.format(name=obj.name, hint_block=hint_block)

    try:
        result = await _run_claude_prompt(
            prompt=prompt,
            output_format="json",
            allowed_tools=["WebFetch", "WebSearch"],
            timeout_seconds=180,
        )
    except _ClaudeCodeError as exc:
        _log.warning("Org research failed for %s (%s): %s", obj.name, org_id, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json(result.result) or {}

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

    await db.commit()
    await db.refresh(obj)
    return obj
