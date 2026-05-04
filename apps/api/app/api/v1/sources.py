"""Job Sources + Leads API.

Sources are user-registered ATS / RSS feeds. The poller worker fans out
into them on a per-source schedule and writes JobLead rows. The leads
inbox is the user's triage UI: bulk-select rows, mark them
interested/watching, which auto-creates a TrackedJob and queues a
score task. Dismissed and expired leads are filtered out by default."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.jobs import JobFetchQueue, TrackedJob
from app.models.sources import JobLead, JobSource
from app.models.user import User
from app.scoring import apply_fit_score_to_job, compute_fit_score
from app.sources import KIND_EXAMPLES, KIND_HINTS, KIND_LABELS
from app.sources.poller import poll_source

router = APIRouter(prefix="/job-sources", tags=["job-sources"])
leads_router = APIRouter(prefix="/job-leads", tags=["job-leads"])


SOURCE_KINDS = set(KIND_LABELS.keys())
LEAD_TRIAGE_STATES = {"interested", "watching", "dismissed"}
LEAD_PROMOTE_STATUSES = {"interested", "watching"}


# Seed sources offered to brand-new users so the /leads inbox isn't a
# blank slate. All shipped DISABLED so the poller doesn't blast every
# new account with noise — the user toggles on whichever ones are
# relevant. A few are wired with regex filters specifically to show off
# what the filter fields can do; copy-paste them as a starting point.
DEFAULT_SEEDS: list[dict] = [
    {
        "kind": "greenhouse",
        "slug_or_url": "anthropic",
        "label": "Anthropic — all roles",
        "filters": None,
        "poll_interval_hours": 24,
        "lead_ttl_hours": 168,
    },
    {
        "kind": "greenhouse",
        "slug_or_url": "stripe",
        "label": "Stripe — engineering only",
        # `(?i)` makes the regex case-insensitive. Anchored alternatives
        # match anywhere in the title — Greenhouse titles are usually
        # "Senior Software Engineer, Payments" / "Staff Engineer" / etc.
        "filters": {
            "title_include": r"(?i)\b(engineer|developer|sre|devops|infra)\b",
        },
        "poll_interval_hours": 24,
        "lead_ttl_hours": 168,
    },
    {
        "kind": "greenhouse",
        "slug_or_url": "discord",
        "label": "Discord — senior+ engineering, US-only",
        "filters": {
            # Combine include + exclude on title and a location include.
            "title_include": r"(?i)\b(senior|staff|principal)\b.*\b(engineer|developer)\b",
            "title_exclude": r"(?i)\b(intern|sales|recruiter|marketing|legal)\b",
            "location_include": r"(?i)united states|remote|san francisco|new york|seattle",
        },
        "poll_interval_hours": 12,
        "lead_ttl_hours": 168,
    },
    {
        "kind": "lever",
        "slug_or_url": "netflix",
        "label": "Netflix — engineering, exclude leadership / contract",
        "filters": {
            "title_include": r"(?i)\b(engineer|developer|sre)\b",
            # Drop director-and-above + non-perm hires.
            "title_exclude": r"(?i)\b(director|vp|vice president|head of|manager|intern|contract|temporary)\b",
        },
        "poll_interval_hours": 24,
        "lead_ttl_hours": 168,
    },
    {
        "kind": "ashby",
        "slug_or_url": "ramp",
        "label": "Ramp — remote or NYC only",
        "filters": {
            "location_include": r"(?i)remote|new york|nyc",
            "title_exclude": r"(?i)\b(intern|sales)\b",
        },
        "poll_interval_hours": 24,
        "lead_ttl_hours": 168,
    },
    {
        "kind": "ashby",
        "slug_or_url": "Linear",
        "label": "Linear — remote-only",
        "filters": {"remote_only": True},
        "poll_interval_hours": 48,
        "lead_ttl_hours": 168,
    },
    {
        "kind": "rss",
        "slug_or_url": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "label": "We Work Remotely — programming, senior+",
        "filters": {
            # Quick way to filter to senior+ specifically.
            "title_include": r"(?i)\b(senior|staff|principal|lead)\b",
        },
        "poll_interval_hours": 12,
        "lead_ttl_hours": 168,
    },
    {
        "kind": "rss",
        "slug_or_url": "https://remoteok.com/remote-jobs.rss",
        "label": "RemoteOK — backend / fullstack",
        "filters": {
            # Multi-keyword OR with word boundaries.
            "title_include": r"(?i)\b(backend|full[\s-]?stack|software engineer|sre|infrastructure)\b",
            "title_exclude": r"(?i)\b(intern|junior|sales|marketing|recruiter)\b",
        },
        "poll_interval_hours": 12,
        "lead_ttl_hours": 168,
    },
]


# ----- Schemas --------------------------------------------------------------


class SourceFiltersIn(BaseModel):
    title_include: Optional[str] = None
    title_exclude: Optional[str] = None
    location_include: Optional[str] = None
    location_exclude: Optional[str] = None
    remote_only: Optional[bool] = None


class SourceIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    slug_or_url: str = Field(min_length=1, max_length=512)
    label: Optional[str] = Field(default=None, max_length=255)
    enabled: bool = True
    filters: Optional[SourceFiltersIn] = None
    poll_interval_hours: int = Field(default=24, ge=1, le=720)
    lead_ttl_hours: int = Field(default=168, ge=1, le=4320)


class SourceUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    enabled: Optional[bool] = None
    filters: Optional[SourceFiltersIn] = None
    poll_interval_hours: Optional[int] = Field(default=None, ge=1, le=720)
    lead_ttl_hours: Optional[int] = Field(default=None, ge=1, le=4320)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    slug_or_url: str
    label: Optional[str] = None
    enabled: bool
    filters: Optional[dict] = None
    poll_interval_hours: int
    lead_ttl_hours: int
    last_polled_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_lead_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # Counts surfaced for the sources list UI.
    new_lead_count: Optional[int] = None
    total_lead_count: Optional[int] = None


class SourceKindExample(BaseModel):
    label: str
    value: str


class SourceKindOut(BaseModel):
    kind: str
    label: str
    hint: str
    examples: list[SourceKindExample] = []


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source_id: int
    source_kind: Optional[str] = None
    source_label: Optional[str] = None
    title: str
    organization_name: Optional[str] = None
    location: Optional[str] = None
    remote_policy: Optional[str] = None
    source_url: Optional[str] = None
    description_md: Optional[str] = None
    posted_at: Optional[datetime] = None
    first_seen_at: datetime
    expires_at: datetime
    state: str
    tracked_job_id: Optional[int] = None
    relevance_score: Optional[int] = None


class LeadActionIn(BaseModel):
    """Bulk action over selected lead IDs."""

    ids: list[int] = Field(min_length=1)
    action: str = Field(description="One of: interested, watching, dismissed.")


class LeadActionOut(BaseModel):
    promoted: int = 0       # leads that became tracked_jobs rows
    dismissed: int = 0
    failed_ids: list[int] = []


# ----- Sources --------------------------------------------------------------


async def _owned_source(
    db: AsyncSession, source_id: int, user_id: int
) -> JobSource:
    row = (
        await db.execute(
            select(JobSource).where(
                JobSource.id == source_id,
                JobSource.user_id == user_id,
                JobSource.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return row


@router.get("/kinds", response_model=list[SourceKindOut])
async def list_kinds() -> list[SourceKindOut]:
    return [
        SourceKindOut(
            kind=k,
            label=KIND_LABELS[k],
            hint=KIND_HINTS[k],
            examples=[
                SourceKindExample(**ex) for ex in KIND_EXAMPLES.get(k, [])
            ],
        )
        for k in sorted(SOURCE_KINDS)
    ]


@router.get("", response_model=list[SourceOut])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SourceOut]:
    rows = (
        await db.execute(
            select(JobSource)
            .where(
                JobSource.user_id == user.id,
                JobSource.deleted_at.is_(None),
            )
            .order_by(JobSource.created_at.desc())
        )
    ).scalars().all()
    if not rows:
        return []

    # Counts per source — small N, so a single grouped query is fine.
    by_id: dict[int, dict[str, int]] = {s.id: {"total": 0, "new": 0} for s in rows}
    counts = (
        await db.execute(
            select(JobLead.source_id, JobLead.state, func.count(JobLead.id))
            .where(JobLead.source_id.in_([s.id for s in rows]))
            .group_by(JobLead.source_id, JobLead.state)
        )
    ).all()
    for source_id, state, n in counts:
        slot = by_id.setdefault(source_id, {"total": 0, "new": 0})
        slot["total"] += n
        if state == "new":
            slot["new"] += n

    out: list[SourceOut] = []
    for s in rows:
        item = SourceOut.model_validate(s)
        item.new_lead_count = by_id.get(s.id, {}).get("new", 0)
        item.total_lead_count = by_id.get(s.id, {}).get("total", 0)
        out.append(item)
    return out


def _validate_slug_or_url(kind: str, raw: str) -> str:
    """Reject empty / whitespace-only values, and enforce that URL kinds
    actually got a URL. Returns the cleaned value."""
    cleaned = (raw or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail="Slug or URL is required.",
        )
    if kind in {"rss", "yc"}:
        if not cleaned.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{kind} sources need a full feed URL "
                    "starting with http:// or https://."
                ),
            )
    else:
        # ATS slugs are short alphanumerics with optional dashes / dots /
        # underscores. If the user pasted a full URL, the per-adapter
        # regexes will pull the slug out — but a bare protocol or empty
        # path means there's nothing usable.
        if cleaned in {"http://", "https://", "/"}:
            raise HTTPException(
                status_code=422,
                detail="Slug looks empty. Paste the company slug or its full board URL.",
            )
    return cleaned


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceOut:
    if payload.kind not in SOURCE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source kind '{payload.kind}'. Allowed: {sorted(SOURCE_KINDS)}",
        )
    cleaned_slug = _validate_slug_or_url(payload.kind, payload.slug_or_url)
    src = JobSource(
        user_id=user.id,
        kind=payload.kind,
        slug_or_url=cleaned_slug,
        label=(payload.label or "").strip() or None,
        enabled=payload.enabled,
        filters=payload.filters.model_dump(exclude_none=True) if payload.filters else None,
        poll_interval_hours=payload.poll_interval_hours,
        lead_ttl_hours=payload.lead_ttl_hours,
    )
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return SourceOut.model_validate(src)


@router.put("/{source_id:int}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceOut:
    src = await _owned_source(db, source_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    if "filters" in data:
        if data["filters"] is None:
            src.filters = None
        else:
            src.filters = data["filters"]
        data.pop("filters")
    for k, v in data.items():
        setattr(src, k, v)
    await db.commit()
    await db.refresh(src)
    return SourceOut.model_validate(src)


@router.delete("/{source_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    src = await _owned_source(db, source_id, user.id)
    src.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


class SeedDefaultsOut(BaseModel):
    created: int
    skipped: int  # rows that already existed for this user
    sources: list[SourceOut]


@router.post("/seed-defaults", response_model=SeedDefaultsOut)
async def seed_defaults(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SeedDefaultsOut:
    """Insert a small library of known-good sources so the leads page
    has something to start from. All seeded rows are created DISABLED
    so the poller doesn't fire until the user toggles them on. Skips
    any (kind, slug_or_url) pair that already exists for this user —
    safe to call repeatedly."""
    existing_rows = (
        await db.execute(
            select(JobSource.kind, JobSource.slug_or_url).where(
                JobSource.user_id == user.id,
                JobSource.deleted_at.is_(None),
            )
        )
    ).all()
    existing = {(k, s) for k, s in existing_rows}

    created_rows: list[JobSource] = []
    skipped = 0
    for seed in DEFAULT_SEEDS:
        key = (seed["kind"], seed["slug_or_url"])
        if key in existing:
            skipped += 1
            continue
        if seed["kind"] not in SOURCE_KINDS:
            # Defensive — shouldn't happen unless the seed list drifts.
            continue
        row = JobSource(
            user_id=user.id,
            kind=seed["kind"],
            slug_or_url=seed["slug_or_url"],
            label=seed.get("label") or None,
            enabled=False,
            filters=seed.get("filters"),
            poll_interval_hours=seed.get("poll_interval_hours", 24),
            lead_ttl_hours=seed.get("lead_ttl_hours", 168),
        )
        db.add(row)
        created_rows.append(row)

    if created_rows:
        await db.commit()
        for row in created_rows:
            await db.refresh(row)

    return SeedDefaultsOut(
        created=len(created_rows),
        skipped=skipped,
        sources=[SourceOut.model_validate(r) for r in created_rows],
    )


@router.post("/{source_id:int}/poll", response_model=SourceOut)
async def poll_now(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceOut:
    """Trigger an immediate poll of one source. Useful for first-time
    setup and for "I added a filter, refresh the inbox" flows. The
    background worker will continue to poll on schedule."""
    src = await _owned_source(db, source_id, user.id)
    inserted, err = await poll_source(db, src)
    if err is not None:
        # Persist the error state but don't 500 — the poll is best-effort.
        await db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Source poll failed: {err}",
        )
    await db.commit()
    await db.refresh(src)
    out = SourceOut.model_validate(src)
    out.new_lead_count = inserted
    return out


# ----- Leads ----------------------------------------------------------------


@leads_router.get("", response_model=list[LeadOut])
async def list_leads(
    state: str = Query(default="new"),
    source_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Substring filter on title/org/location."),
    remote_only: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LeadOut]:
    """List leads by state. Default is `new` — the inbox view. Pass
    `state=all` to skip the state filter."""
    stmt = (
        select(JobLead, JobSource.kind, JobSource.label)
        .join(JobSource, JobSource.id == JobLead.source_id)
        .where(JobLead.user_id == user.id)
        .order_by(
            # Newest first inside each state.
            JobLead.first_seen_at.desc()
        )
        .limit(limit)
    )
    if state and state != "all":
        stmt = stmt.where(JobLead.state == state)
    if source_id is not None:
        stmt = stmt.where(JobLead.source_id == source_id)
    if remote_only:
        stmt = stmt.where(JobLead.remote_policy == "remote")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (JobLead.title.ilike(like))
            | (JobLead.organization_name.ilike(like))
            | (JobLead.location.ilike(like))
        )
    rows = (await db.execute(stmt)).all()
    out: list[LeadOut] = []
    for lead, kind, label in rows:
        item = LeadOut.model_validate(lead)
        item.source_kind = kind
        item.source_label = label
        out.append(item)
    return out


async def _promote_lead(
    db: AsyncSession,
    lead: JobLead,
    target_status: str,
    user: User,
) -> Optional[int]:
    """Create a TrackedJob from the lead, run the deterministic fit-score
    against it so the row lands with a real number, and queue a Claude
    JD-analysis task for the qualitative side. Returns the new
    tracked_job id."""
    tj = TrackedJob(
        user_id=user.id,
        title=lead.title[:255],
        job_description=lead.description_md or None,
        source_url=lead.source_url or None,
        source_platform=f"source:{lead.source_id}",
        location=lead.location or None,
        remote_policy=lead.remote_policy if lead.remote_policy in {"onsite", "hybrid", "remote"} else None,
        status=target_status,
        date_discovered=date.today(),
    )
    db.add(tj)
    await db.flush()
    lead.state = "promoted"
    lead.tracked_job_id = tj.id
    # Deterministic score — cheap, reads from the user's prefs/criteria.
    result = await compute_fit_score(db, user, tj)
    apply_fit_score_to_job(tj, result)
    # Enqueue an enrich-fetch (so the URL flow's organization-context +
    # full skill-list extraction runs against this row, not just the
    # cached lead body) and a JD-analysis task (qualitative strengths
    # / gaps / red flags). The fetch handler runs in update mode when
    # given `tracked_job_id` and only fills empty fields, so the
    # user's lead-promotion choices (status etc.) survive.
    if tj.source_url:
        db.add(
            JobFetchQueue(
                user_id=user.id,
                kind="fetch",
                label=f"Enrich lead → {tj.title[:80]}"[:512],
                url=tj.source_url,
                payload={"tracked_job_id": tj.id},
                state="queued",
            )
        )
    db.add(
        JobFetchQueue(
            user_id=user.id,
            kind="score",
            label=f"Score lead → {tj.title[:80]}"[:512],
            url="",  # legacy NOT-NULL column; empty for non-fetch kinds
            payload={"tracked_job_id": tj.id},
            state="queued",
        )
    )
    return tj.id


@leads_router.post("/action", response_model=LeadActionOut)
async def lead_bulk_action(
    payload: LeadActionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LeadActionOut:
    """Bulk triage. `action` ∈ {interested, watching, dismissed}.
    interested / watching auto-create a tracked_jobs row at that
    status, queue a score task, and flip the lead to `promoted`."""
    action = payload.action.strip().lower()
    if action not in LEAD_TRIAGE_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown action '{action}'. Allowed: {sorted(LEAD_TRIAGE_STATES)}",
        )
    rows = (
        await db.execute(
            select(JobLead).where(
                JobLead.id.in_(payload.ids),
                JobLead.user_id == user.id,
            )
        )
    ).scalars().all()
    found_ids = {r.id for r in rows}
    failed = [i for i in payload.ids if i not in found_ids]
    promoted = 0
    dismissed = 0
    for lead in rows:
        if action == "dismissed":
            lead.state = "dismissed"
            dismissed += 1
            continue
        # interested / watching → promote to tracked_jobs.
        if lead.state == "promoted" and lead.tracked_job_id:
            # Already promoted — nothing to do, treat as success.
            continue
        await _promote_lead(db, lead, action, user)
        promoted += 1
    await db.commit()
    return LeadActionOut(
        promoted=promoted,
        dismissed=dismissed,
        failed_ids=failed,
    )


def register(app) -> None:
    """Convenience for main.py to mount both routers under the same prefix."""
    app.include_router(router, prefix="/api/v1")
    app.include_router(leads_router, prefix="/api/v1")
