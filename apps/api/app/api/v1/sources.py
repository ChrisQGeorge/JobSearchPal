"""Job Sources + Leads API.

Sources are user-registered ATS / RSS feeds. The poller worker fans out
into them on a per-source schedule and writes JobLead rows. The leads
inbox is the user's triage UI: bulk-select rows, mark them
interested/watching, which auto-creates a TrackedJob and queues a
score task. Dismissed and expired leads are filtered out by default."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
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
# Lead triage actions surfaced on the inbox.
#   "review"     → promote to a TrackedJob at status=to_review (the
#                  user reviews the row in the tracker queue, exactly
#                  like a manually-pasted URL).
#   "dismissed"  → drop the lead without creating anything.
# `interested` / `watching` are no longer accepted — the user explicitly
# asked that lead-promotions land at to_review so the review queue
# gates everything new before it inflates active-application counts.
LEAD_TRIAGE_STATES = {"review", "dismissed"}
PROMOTED_STATUS = "to_review"


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
    # Bright Data extras. `dataset_id` overrides the kind's default
    # dataset (any brightdata_* kind). The rest belong to
    # kind=brightdata_keyword: `inputs` is the saved query — one row
    # per discovery input, same columns as the dataset's CSV
    # (location/keyword/country/time_range/company/location_radius) —
    # and `time_range_override` replaces every row's time_range at run
    # time ("Past week" by default; empty string = use row values).
    dataset_id: Optional[str] = Field(default=None, max_length=64)
    inputs: Optional[list[dict]] = None
    time_range_override: Optional[str] = Field(default=None, max_length=32)


class SourceIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    slug_or_url: str = Field(min_length=1, max_length=512)
    label: Optional[str] = Field(default=None, max_length=255)
    enabled: bool = True
    filters: Optional[SourceFiltersIn] = None
    poll_interval_hours: int = Field(default=24, ge=1, le=720)
    lead_ttl_hours: int = Field(default=168, ge=1, le=4320)
    max_leads_per_poll: int = Field(default=100, ge=1, le=10000)


class SourceUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    enabled: Optional[bool] = None
    filters: Optional[SourceFiltersIn] = None
    poll_interval_hours: Optional[int] = Field(default=None, ge=1, le=720)
    lead_ttl_hours: Optional[int] = Field(default=None, ge=1, le=4320)
    max_leads_per_poll: Optional[int] = Field(default=None, ge=1, le=10000)


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
    max_leads_per_poll: int = 100
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


def _prepare_keyword_filters(filters: Optional[dict]) -> dict:
    """Validate + normalize the saved query for kind=brightdata_keyword:
    input rows are cleaned to the dataset's columns (rows without a
    keyword dropped), and time_range_override defaults to "Past week" so
    every run imports the previous week's listings unless the user
    explicitly picked another range (empty string = use each row's own
    time_range)."""
    from app.sources.brightdata import KEYWORD_TIME_RANGES, clean_keyword_inputs

    f = dict(filters or {})
    cleaned = clean_keyword_inputs(f.get("inputs"))
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail=(
                "A keyword-discovery source needs at least one input row "
                "with a keyword. Add rows in the editor or upload the "
                "input CSV."
            ),
        )
    f["inputs"] = cleaned
    override = f.get("time_range_override")
    if override is None:
        f["time_range_override"] = "Past week"
    elif override and override not in KEYWORD_TIME_RANGES:
        raise HTTPException(
            status_code=422,
            detail=(
                "time_range_override must be one of "
                f"{list(KEYWORD_TIME_RANGES)}, or empty to use each "
                "row's own time_range."
            ),
        )
    return f


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
    filters = (
        payload.filters.model_dump(exclude_none=True) if payload.filters else None
    )
    if payload.kind == "brightdata_keyword":
        filters = _prepare_keyword_filters(filters)
    src = JobSource(
        user_id=user.id,
        kind=payload.kind,
        slug_or_url=cleaned_slug,
        label=(payload.label or "").strip() or None,
        enabled=payload.enabled,
        filters=filters,
        poll_interval_hours=payload.poll_interval_hours,
        lead_ttl_hours=payload.lead_ttl_hours,
        max_leads_per_poll=payload.max_leads_per_poll,
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
        if src.kind == "brightdata_keyword":
            new_filters = _prepare_keyword_filters(data["filters"])
            # Editing mid-run must not drop a parked (already paid-for)
            # snapshot — the editor doesn't round-trip these keys.
            old = src.filters if isinstance(src.filters, dict) else {}
            for k in ("pending_snapshot_id", "pending_since"):
                if old.get(k):
                    new_filters[k] = old[k]
            src.filters = new_filters
        elif data["filters"] is None:
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


class KeywordCsvOut(BaseModel):
    inputs: list[dict]
    skipped_rows: int = 0


@router.post("/parse-keyword-csv", response_model=KeywordCsvOut)
async def parse_keyword_csv(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> KeywordCsvOut:
    """Parse a Bright Data keyword-discovery input CSV (the dataset's
    own format: location,keyword,country,time_range,company,
    location_radius) into input rows for the source editor. Handles the
    dataset's quoting quirks (e.g. \"\"\"python developer\"\"\" → a
    keyword with literal quotes for exact-phrase search). Nothing is
    saved — the rows are returned for the editor to hold until the
    source is saved."""
    from app.sources.brightdata import clean_keyword_inputs

    raw = await file.read()
    if len(raw) > 1_000_000:
        raise HTTPException(status_code=413, detail="CSV larger than 1 MB.")
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [fn for fn in (reader.fieldnames or []) if fn]
    norm = {fn: fn.strip().lower().replace(" ", "_") for fn in fieldnames}
    if "keyword" not in norm.values():
        raise HTTPException(
            status_code=422,
            detail=(
                "CSV is missing a 'keyword' column. Expected the Bright "
                "Data input header: location,keyword,country,time_range,"
                "company,location_radius."
            ),
        )
    rows: list[dict] = []
    for rec in reader:
        rows.append({norm.get(k, k): v for k, v in rec.items() if k})
    cleaned = clean_keyword_inputs(rows)
    nonempty = sum(
        1 for r in rows if any(str(v or "").strip() for v in r.values())
    )
    return KeywordCsvOut(
        inputs=cleaned, skipped_rows=max(0, nonempty - len(cleaned))
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
    inserted, err = await poll_source(db, src, quick=True)
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
    user: User,
) -> Optional[int]:
    """Promote a lead by enqueueing a fetch task on its source_url
    with `desired_status=to_review`. Same flow as pasting a URL on
    the tracker — the fetch worker creates the TrackedJob, runs the
    JD analyzer / fit scoring downstream, and the lead's
    `tracked_job_id` is back-filled when the worker finishes (via
    `lead_id` in the queue row's payload).

    Fallback: if the lead has no source_url (rare for ATS adapters
    but possible for some RSS feeds), we create a TrackedJob
    immediately from the cached body since there's nothing to fetch.
    Either way the new row lands at status=to_review so the review
    queue gates it before it inflates active-application counts.
    """
    target_status = PROMOTED_STATUS
    if not lead.source_url:
        # No URL to fetch — fall back to immediate-create from the
        # cached body. Mirrors the behavior the user had before, just
        # for this edge case.
        tj = TrackedJob(
            user_id=user.id,
            title=lead.title[:255],
            job_description=lead.description_md or None,
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
        result = await compute_fit_score(db, user, tj)
        apply_fit_score_to_job(tj, result)
        return tj.id

    # Standard path — queue a fetch task and let the worker handle
    # everything (TrackedJob creation, org-context extraction, skill
    # lists, JD analysis). lead_id in the payload tells the fetch
    # handler to back-link the new TrackedJob onto this lead row.
    payload: dict = {"lead_id": lead.id}
    raw = lead.raw_payload if isinstance(lead.raw_payload, dict) else {}
    if raw.get("job_posting_id") and (raw.get("job_title") or raw.get("title")):
        # Bright Data LinkedIn record: the stored payload is richer than
        # what a fresh (often login-walled) page fetch + LLM parse would
        # get, so the worker builds the job straight from it.
        payload["prefetched"] = "brightdata_linkedin"
    db.add(
        JobFetchQueue(
            user_id=user.id,
            kind="fetch",
            label=f"Lead → {lead.title[:80]}"[:512],
            url=lead.source_url,
            desired_status=target_status,
            payload=payload,
            state="queued",
        )
    )
    lead.state = "promoted"
    # tracked_job_id stays null until the fetch worker creates the row
    # and back-links via lead_id in the payload.
    return None


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
        # action == "review" — promote to tracked_jobs at to_review.
        if lead.state == "promoted" and lead.tracked_job_id:
            # Already promoted — nothing to do, treat as success.
            continue
        await _promote_lead(db, lead, user)
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
