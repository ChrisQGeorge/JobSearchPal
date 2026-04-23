"""Job Tracker: tracked jobs, application events, interview rounds.

Status transitions are free-form (any → any) per SRS REQ-FUNC-JOBS-001 but
always emit an ApplicationEvent so the audit/history is preserved.
"""

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status as http_status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.jobs import (
    ApplicationEvent,
    InterviewArtifact,
    InterviewRound,
    JobFetchQueue,
    Organization,
    TrackedJob,
)
from app.models.user import User
from app.schemas.jobs import (
    ApplicationEventIn,
    ApplicationEventOut,
    ARTIFACT_KINDS,
    FetchFromUrlIn,
    FetchedJobInfo,
    InterviewArtifactIn,
    InterviewArtifactOut,
    InterviewRoundIn,
    InterviewRoundOut,
    JOB_STATUSES,
    JobFetchQueueIn,
    JobFetchQueueOut,
    PRIORITIES,
    REMOTE_POLICIES,
    TrackedJobIn,
    TrackedJobOut,
    TrackedJobSummary,
    TrackedJobUpdate,
)
from app.skills.runner import ClaudeCodeError, run_claude_prompt

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _validate_status(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if v not in JOB_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown status '{v}'. Allowed: {sorted(JOB_STATUSES)}",
        )
    return v


def _validate_simple(v: Optional[str], allowed: set[str], label: str) -> Optional[str]:
    if v is None or v == "":
        return None
    if v not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown {label} '{v}'. Allowed: {sorted(allowed)}",
        )
    return v


async def _get_owned_job(
    db: AsyncSession, job_id: int, user_id: int
) -> TrackedJob:
    stmt = select(TrackedJob).where(
        TrackedJob.id == job_id,
        TrackedJob.user_id == user_id,
        TrackedJob.deleted_at.is_(None),
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _org_names_for(
    db: AsyncSession, ids: set[int]
) -> dict[int, str]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Organization.id, Organization.name).where(
                Organization.id.in_(ids)
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows}


# --- TrackedJob list / create / detail / update / delete --------------------

@router.get("", response_model=list[TrackedJobSummary])
async def list_jobs(
    status: Optional[str] = Query(default=None, description="Filter to one status"),
    q: Optional[str] = Query(default=None, description="Prefix search on title"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TrackedJobSummary]:
    stmt = select(TrackedJob).where(
        TrackedJob.user_id == user.id, TrackedJob.deleted_at.is_(None)
    )
    if status:
        _validate_status(status)
        stmt = stmt.where(TrackedJob.status == status)
    if q:
        stmt = stmt.where(TrackedJob.title.ilike(f"%{q}%"))
    stmt = stmt.order_by(TrackedJob.updated_at.desc())
    jobs = list((await db.execute(stmt)).scalars().all())

    # Hydrate organization names and interview-round counts in bulk.
    org_names = await _org_names_for(
        db, {j.organization_id for j in jobs if j.organization_id}
    )

    # Rounds aggregate: count + latest outcome per job.
    if jobs:
        job_ids = [j.id for j in jobs]
        rounds_count_rows = (
            await db.execute(
                select(
                    InterviewRound.tracked_job_id,
                    func.count(InterviewRound.id),
                )
                .where(
                    InterviewRound.tracked_job_id.in_(job_ids),
                    InterviewRound.deleted_at.is_(None),
                )
                .group_by(InterviewRound.tracked_job_id)
            )
        ).all()
        counts_by_job = {row[0]: row[1] for row in rounds_count_rows}

        # Latest round outcome per job (by round_number desc, then created_at).
        latest_rounds = (
            await db.execute(
                select(InterviewRound)
                .where(
                    InterviewRound.tracked_job_id.in_(job_ids),
                    InterviewRound.deleted_at.is_(None),
                )
                .order_by(
                    InterviewRound.tracked_job_id,
                    InterviewRound.round_number.desc(),
                    InterviewRound.id.desc(),
                )
            )
        ).scalars().all()
        latest_by_job: dict[int, str] = {}
        for r in latest_rounds:
            latest_by_job.setdefault(r.tracked_job_id, r.outcome)
    else:
        counts_by_job = {}
        latest_by_job = {}

    out: list[TrackedJobSummary] = []
    for j in jobs:
        fit_score: Optional[int] = None
        fs = j.fit_summary
        if isinstance(fs, dict):
            raw = fs.get("score")
            if isinstance(raw, (int, float)):
                fit_score = int(raw)
        red_flag_count = 0
        jda = j.jd_analysis
        if isinstance(jda, dict):
            rfs = jda.get("red_flags")
            if isinstance(rfs, list):
                red_flag_count = len(rfs)
        out.append(
            TrackedJobSummary(
                id=j.id,
                title=j.title,
                status=j.status,
                priority=j.priority,
                remote_policy=j.remote_policy,
                location=j.location,
                organization_id=j.organization_id,
                organization_name=org_names.get(j.organization_id)
                if j.organization_id
                else None,
                date_applied=j.date_applied,
                date_discovered=j.date_discovered,
                updated_at=j.updated_at,
                rounds_count=counts_by_job.get(j.id, 0),
                latest_round_outcome=latest_by_job.get(j.id),
                salary_min=j.salary_min,
                salary_max=j.salary_max,
                salary_currency=j.salary_currency,
                experience_level=j.experience_level,
                experience_years_min=j.experience_years_min,
                experience_years_max=j.experience_years_max,
                employment_type=j.employment_type,
                fit_score=fit_score,
                red_flag_count=red_flag_count,
            )
        )
    return out


@router.post(
    "",
    response_model=TrackedJobOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_job(
    payload: TrackedJobIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrackedJob:
    data = payload.model_dump(exclude_unset=True)
    data["status"] = _validate_status(data.get("status")) or "watching"
    data["priority"] = _validate_simple(
        data.get("priority"), PRIORITIES, "priority"
    )
    data["remote_policy"] = _validate_simple(
        data.get("remote_policy"), REMOTE_POLICIES, "remote_policy"
    )
    if "date_discovered" not in data:
        data["date_discovered"] = date.today()

    job = TrackedJob(user_id=user.id, **data)
    db.add(job)
    await db.flush()

    # Every new job starts with a status event — useful for the activity feed.
    db.add(
        ApplicationEvent(
            tracked_job_id=job.id,
            event_type="note",
            event_date=datetime.now(tz=timezone.utc),
            details_md=f"Created with status `{job.status}`.",
        )
    )
    await db.commit()
    await db.refresh(job)

    org_names = await _org_names_for(
        db, {job.organization_id} if job.organization_id else set()
    )
    job.organization_name = org_names.get(job.organization_id)  # type: ignore[attr-defined]
    return job


@router.get("/{job_id:int}", response_model=TrackedJobOut)
async def get_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrackedJob:
    job = await _get_owned_job(db, job_id, user.id)
    org_names = await _org_names_for(
        db, {job.organization_id} if job.organization_id else set()
    )
    job.organization_name = org_names.get(job.organization_id)  # type: ignore[attr-defined]
    return job


@router.put("/{job_id:int}", response_model=TrackedJobOut)
async def update_job(
    job_id: int,
    payload: TrackedJobUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrackedJob:
    job = await _get_owned_job(db, job_id, user.id)
    data = payload.model_dump(exclude_unset=True)

    _validate_status(data.get("status"))
    if data.get("priority") is not None:
        _validate_simple(data["priority"], PRIORITIES, "priority")
    if data.get("remote_policy") is not None:
        _validate_simple(data["remote_policy"], REMOTE_POLICIES, "remote_policy")

    prior_status = job.status
    for k, v in data.items():
        setattr(job, k, v)

    # Auto-emit an ApplicationEvent on status transitions so the activity feed
    # has an audit trail without the user having to log anything by hand.
    if "status" in data and data["status"] != prior_status:
        db.add(
            ApplicationEvent(
                tracked_job_id=job.id,
                event_type=_status_to_event_type(data["status"]),
                event_date=datetime.now(tz=timezone.utc),
                details_md=f"Status changed: `{prior_status}` → `{data['status']}`.",
            )
        )
        # Convenience: the first move into `applied` stamps date_applied if
        # the user hasn't already set it.
        if data["status"] == "applied" and job.date_applied is None:
            job.date_applied = date.today()
        if (
            data["status"] in {"won", "lost", "withdrawn", "ghosted", "archived", "not_interested"}
            and job.date_closed is None
        ):
            job.date_closed = date.today()

    await db.commit()
    await db.refresh(job)

    org_names = await _org_names_for(
        db, {job.organization_id} if job.organization_id else set()
    )
    job.organization_name = org_names.get(job.organization_id)  # type: ignore[attr-defined]
    return job


def _status_to_event_type(status: str) -> str:
    """Best-fit mapping from status → event_type for the activity feed."""
    return {
        "applied": "applied",
        "responded": "responded",
        "screening": "phone_screen",
        "interviewing": "interview_scheduled",
        "assessment": "assessment_assigned",
        "offer": "offer_received",
        "won": "offer_accepted",
        "lost": "rejection",
        "withdrawn": "withdrawal",
        "ghosted": "note",
        "archived": "note",
        "watching": "note",
        "interested": "note",
        "not_interested": "note",
    }.get(status, "note")


@router.delete("/{job_id:int}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    job = await _get_owned_job(db, job_id, user.id)
    job.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# --- ApplicationEvents (activity feed) --------------------------------------

@router.get("/{job_id:int}/events", response_model=list[ApplicationEventOut])
async def list_events(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ApplicationEvent]:
    await _get_owned_job(db, job_id, user.id)
    stmt = (
        select(ApplicationEvent)
        .where(ApplicationEvent.tracked_job_id == job_id)
        .order_by(ApplicationEvent.event_date.desc(), ApplicationEvent.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/{job_id:int}/events",
    response_model=ApplicationEventOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_event(
    job_id: int,
    payload: ApplicationEventIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApplicationEvent:
    await _get_owned_job(db, job_id, user.id)
    ev = ApplicationEvent(
        tracked_job_id=job_id,
        event_type=payload.event_type,
        event_date=payload.event_date or datetime.now(tz=timezone.utc),
        details_md=payload.details_md,
        related_round_id=payload.related_round_id,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return ev


# --- InterviewRounds --------------------------------------------------------

@router.get("/{job_id:int}/rounds", response_model=list[InterviewRoundOut])
async def list_rounds(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InterviewRound]:
    await _get_owned_job(db, job_id, user.id)
    stmt = (
        select(InterviewRound)
        .where(
            InterviewRound.tracked_job_id == job_id,
            InterviewRound.deleted_at.is_(None),
        )
        .order_by(InterviewRound.round_number.asc(), InterviewRound.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/{job_id:int}/rounds",
    response_model=InterviewRoundOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_round(
    job_id: int,
    payload: InterviewRoundIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewRound:
    await _get_owned_job(db, job_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    data.setdefault("outcome", "pending")
    rnd = InterviewRound(tracked_job_id=job_id, **data)
    db.add(rnd)
    await db.commit()
    await db.refresh(rnd)
    return rnd


async def _get_owned_round(
    db: AsyncSession, round_id: int, job_id: int, user_id: int
) -> InterviewRound:
    # Validate the round belongs to the user's job.
    await _get_owned_job(db, job_id, user_id)
    stmt = select(InterviewRound).where(
        InterviewRound.id == round_id,
        InterviewRound.tracked_job_id == job_id,
        InterviewRound.deleted_at.is_(None),
    )
    rnd = (await db.execute(stmt)).scalar_one_or_none()
    if rnd is None:
        raise HTTPException(status_code=404, detail="Interview round not found")
    return rnd


@router.put("/{job_id:int}/rounds/{round_id:int}", response_model=InterviewRoundOut)
async def update_round(
    job_id: int,
    round_id: int,
    payload: InterviewRoundIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewRound:
    rnd = await _get_owned_round(db, round_id, job_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rnd, k, v)
    await db.commit()
    await db.refresh(rnd)
    return rnd


@router.delete(
    "/{job_id:int}/rounds/{round_id:int}", status_code=http_status.HTTP_204_NO_CONTENT
)
async def delete_round(
    job_id: int,
    round_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    rnd = await _get_owned_round(db, round_id, job_id, user.id)
    rnd.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# --- InterviewArtifacts -----------------------------------------------------

def _validate_artifact_kind(v: str) -> str:
    if v not in ARTIFACT_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown artifact kind '{v}'. Allowed: {sorted(ARTIFACT_KINDS)}",
        )
    return v


async def _get_owned_artifact(
    db: AsyncSession, artifact_id: int, job_id: int, user_id: int
) -> InterviewArtifact:
    await _get_owned_job(db, job_id, user_id)
    stmt = select(InterviewArtifact).where(
        InterviewArtifact.id == artifact_id,
        InterviewArtifact.tracked_job_id == job_id,
        InterviewArtifact.deleted_at.is_(None),
    )
    art = (await db.execute(stmt)).scalar_one_or_none()
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return art


@router.get("/{job_id:int}/artifacts", response_model=list[InterviewArtifactOut])
async def list_artifacts(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InterviewArtifact]:
    await _get_owned_job(db, job_id, user.id)
    stmt = (
        select(InterviewArtifact)
        .where(
            InterviewArtifact.tracked_job_id == job_id,
            InterviewArtifact.deleted_at.is_(None),
        )
        .order_by(InterviewArtifact.created_at.desc(), InterviewArtifact.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/{job_id:int}/artifacts",
    response_model=InterviewArtifactOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_artifact(
    job_id: int,
    payload: InterviewArtifactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewArtifact:
    await _get_owned_job(db, job_id, user.id)
    _validate_artifact_kind(payload.kind)
    if payload.interview_round_id is not None:
        await _get_owned_round(db, payload.interview_round_id, job_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    art = InterviewArtifact(tracked_job_id=job_id, **data)
    db.add(art)
    await db.commit()
    await db.refresh(art)
    return art


@router.put(
    "/{job_id:int}/artifacts/{artifact_id:int}",
    response_model=InterviewArtifactOut,
)
async def update_artifact(
    job_id: int,
    artifact_id: int,
    payload: InterviewArtifactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewArtifact:
    art = await _get_owned_artifact(db, artifact_id, job_id, user.id)
    _validate_artifact_kind(payload.kind)
    if payload.interview_round_id is not None:
        await _get_owned_round(db, payload.interview_round_id, job_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(art, k, v)
    await db.commit()
    await db.refresh(art)
    return art


@router.delete(
    "/{job_id:int}/artifacts/{artifact_id:int}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def delete_artifact(
    job_id: int,
    artifact_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    art = await _get_owned_artifact(db, artifact_id, job_id, user.id)
    art.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# --- Interview prep / retrospective skills ----------------------------------

_INTERVIEW_PREP_PROMPT = """You are preparing the user for an interview round.
Pull what you need from the API — job description, JD analysis, their skills /
work history, company research, any existing prep notes. Then draft a prep
doc.

Environment: $JSP_API_BASE_URL and $JSP_API_TOKEN (bearer).
Useful calls:
  curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" "$JSP_API_BASE_URL/api/v1/jobs/{job_id}"
  curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" "$JSP_API_BASE_URL/api/v1/jobs/{job_id}/rounds"
  curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" "$JSP_API_BASE_URL/api/v1/history/skills"
  curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" "$JSP_API_BASE_URL/api/v1/history/work"
  curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" "$JSP_API_BASE_URL/api/v1/organizations/$ORG_ID"

Target round
------------
job_id: {job_id}
round_id: {round_id}
round_number: {round_number}
round_type: {round_type}
scheduled_at: {scheduled_at}
format: {format_}
existing prep_notes_md:
---
{prep_notes_md}
---

Return ONE JSON object, no prose, no markdown fences:

{{
  "prep_doc_md": string,        // the full prep doc the user will read
  "focus_areas": string[],      // 3-6 bullet points — concrete topics to drill
  "likely_questions": string[], // 5-10 realistic questions they should prep for
  "stories_to_tell": string[],  // bullet points referencing specific history
                                // entries ("the Acme rewrite", not "a rewrite")
  "questions_to_ask": string[], // smart questions the user should ask them
  "warning": string | null      // concrete gaps or concerns, or null
}}
"""


_INTERVIEW_RETRO_PROMPT = """You are helping the user write an interview
retrospective. They just finished a round; you'll produce structured notes
they can reference later and that the job-fit-scorer / strategy-advisor
skills can read.

Round details
-------------
job_id: {job_id}
round_id: {round_id}
round_number: {round_number}
round_type: {round_type}
outcome: {outcome}
self_rating: {self_rating}
existing notes_md:
---
{notes_md}
---

User's raw recap of the round (write-up they pasted or dictated):
---
{user_recap}
---

Return ONE JSON object, no prose, no markdown fences:

{{
  "retrospective_md": string,   // clean structured prose retrospective
  "went_well": string[],        // what the candidate executed on
  "went_poorly": string[],      // what didn't land
  "skill_gaps_observed": string[], // gaps surfaced by the questions asked
  "topics_to_brush_up": string[],
  "followup_action": string | null, // one concrete next action (e.g. "send
                                    // Priya the example from the rebuild")
  "rerun_confidence": number | null,  // 0-100, the candidate's confidence in
                                    // passing if they had to retake this round
  "warning": string | null
}}
"""


class InterviewPrepIn(BaseModel):
    extra_notes: Optional[str] = None


class InterviewPrepOut(BaseModel):
    prep_doc_md: str
    focus_areas: list[str] = []
    likely_questions: list[str] = []
    stories_to_tell: list[str] = []
    questions_to_ask: list[str] = []
    warning: Optional[str] = None


class InterviewRetroIn(BaseModel):
    user_recap: str = Field(min_length=1)
    self_rating: Optional[int] = Field(default=None, ge=1, le=5)


class InterviewRetroOut(BaseModel):
    retrospective_md: str
    went_well: list[str] = []
    went_poorly: list[str] = []
    skill_gaps_observed: list[str] = []
    topics_to_brush_up: list[str] = []
    followup_action: Optional[str] = None
    rerun_confidence: Optional[int] = None
    warning: Optional[str] = None


@router.post(
    "/{job_id:int}/rounds/{round_id:int}/prep",
    response_model=InterviewPrepOut,
)
async def interview_prep(
    job_id: int,
    round_id: int,
    payload: InterviewPrepIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewPrepOut:
    from app.core.security import create_access_token

    rnd = await _get_owned_round(db, round_id, job_id, user.id)

    prompt = _INTERVIEW_PREP_PROMPT.format(
        job_id=job_id,
        round_id=round_id,
        round_number=rnd.round_number,
        round_type=rnd.round_type or "(unspecified)",
        scheduled_at=rnd.scheduled_at.isoformat() if rnd.scheduled_at else "(unscheduled)",
        format_=rnd.format or "(unspecified)",
        prep_notes_md=rnd.prep_notes_md or "(none yet)",
    )
    if payload.extra_notes and payload.extra_notes.strip():
        prompt += "\n\nUser guidance for this prep pass:\n" + payload.extra_notes.strip()

    api_token = create_access_token(
        subject=str(user.id), extra={"purpose": "interview_prep"}
    )

    from app.skills.queue_bus import run_claude_to_bus

    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source="interview_prep",
            item_id=f"round:{round_id}",
            label=f"Interview prep: round {rnd.round_number}",
            allowed_tools=["Bash"],
            timeout_seconds=180,
            extra_env={
                "JSP_API_BASE_URL": "http://localhost:8000",
                "JSP_API_TOKEN": api_token,
            },
        )
    except ClaudeCodeError as exc:
        log.warning("interview-prep failed for round %s: %s", round_id, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json_object(final_text) or {}
    prep_doc = (data.get("prep_doc_md") or "").strip()
    if not prep_doc:
        raise HTTPException(
            status_code=502, detail="Prep skill returned no document."
        )

    # Persist onto the round's prep_notes_md so the user sees it on the tab.
    rnd.prep_notes_md = prep_doc
    await db.commit()

    return InterviewPrepOut(
        prep_doc_md=prep_doc,
        focus_areas=list(data.get("focus_areas") or [])[:8],
        likely_questions=list(data.get("likely_questions") or [])[:12],
        stories_to_tell=list(data.get("stories_to_tell") or [])[:8],
        questions_to_ask=list(data.get("questions_to_ask") or [])[:8],
        warning=data.get("warning"),
    )


@router.post(
    "/{job_id:int}/rounds/{round_id:int}/retrospective",
    response_model=InterviewRetroOut,
)
async def interview_retrospective(
    job_id: int,
    round_id: int,
    payload: InterviewRetroIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewRetroOut:
    rnd = await _get_owned_round(db, round_id, job_id, user.id)

    prompt = _INTERVIEW_RETRO_PROMPT.format(
        job_id=job_id,
        round_id=round_id,
        round_number=rnd.round_number,
        round_type=rnd.round_type or "(unspecified)",
        outcome=rnd.outcome or "unknown",
        self_rating=rnd.self_rating if rnd.self_rating is not None else "(none)",
        notes_md=rnd.notes_md or "(none yet)",
        user_recap=payload.user_recap,
    )

    from app.skills.queue_bus import run_claude_to_bus

    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source="interview_retro",
            item_id=f"round:{round_id}",
            label=f"Retro: round {rnd.round_number}",
            allowed_tools=[],
            timeout_seconds=120,
        )
    except ClaudeCodeError as exc:
        log.warning("interview-retro failed for round %s: %s", round_id, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json_object(final_text) or {}
    retro_md = (data.get("retrospective_md") or "").strip()
    if not retro_md:
        raise HTTPException(
            status_code=502, detail="Retrospective skill returned no document."
        )

    # Append to the round's notes_md (never overwrite raw user input).
    ts = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    block = f"\n\n---\n## Retrospective ({ts})\n\n{retro_md}\n"
    rnd.notes_md = (rnd.notes_md or "") + block
    if payload.self_rating is not None:
        rnd.self_rating = payload.self_rating
    await db.commit()

    return InterviewRetroOut(
        retrospective_md=retro_md,
        went_well=list(data.get("went_well") or [])[:8],
        went_poorly=list(data.get("went_poorly") or [])[:8],
        skill_gaps_observed=list(data.get("skill_gaps_observed") or [])[:8],
        topics_to_brush_up=list(data.get("topics_to_brush_up") or [])[:8],
        followup_action=data.get("followup_action"),
        rerun_confidence=(
            int(data["rerun_confidence"])
            if isinstance(data.get("rerun_confidence"), (int, float))
            else None
        ),
        warning=data.get("warning"),
    )


@router.post(
    "/{job_id:int}/artifacts/upload",
    response_model=InterviewArtifactOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def upload_artifact(
    job_id: int,
    file: UploadFile = File(...),
    kind: str = Form(default="other"),
    title: Optional[str] = Form(default=None),
    interview_round_id: Optional[int] = Form(default=None),
    tags: Optional[str] = Form(default=None),  # comma-separated
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InterviewArtifact:
    """Multipart upload variant for interview artifacts — lets the user drop
    in a whiteboard photo, take-home .pdf, offer letter, etc. without having
    to host the file elsewhere first.

    Stores the raw bytes under `/app/uploads/artifacts/<user_id>/<uuid>_<name>`
    and sets `file_url` to the streaming endpoint path (`/api/v1/jobs/{id}/
    artifacts/{id}/file`). For plain-text / markdown uploads, also decodes
    into `content_md` so the viewer can show the content inline.
    """
    _validate_artifact_kind(kind)
    await _get_owned_job(db, job_id, user.id)
    if interview_round_id is not None:
        await _get_owned_round(db, interview_round_id, job_id, user.id)

    import mimetypes as _mt
    import uuid as _uuid
    from pathlib import Path as _Path

    _UPLOADS_ROOT = _Path("/app/uploads")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="File too large (max 25 MB).",
        )

    original_name = _Path(file.filename or "artifact").name
    original_name = re.sub(r"[^\w.\-]+", "_", original_name)[:120] or "artifact"
    mime = (
        file.content_type
        or _mt.guess_type(original_name)[0]
        or "application/octet-stream"
    )

    dest_dir = _UPLOADS_ROOT / "artifacts" / str(user.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{_uuid.uuid4().hex[:12]}_{original_name}"
    dest_path = dest_dir / stored_name
    dest_path.write_bytes(data)

    # Plain-text / markdown → also inline in content_md for the collapsed view.
    from app.skills.doc_text import extract_text as _extract_text
    content_md = _extract_text(data, mime, original_name)

    tag_list: Optional[list[str]] = None
    if tags and tags.strip():
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    effective_title = (title or "").strip() or _Path(original_name).stem or "Artifact"

    art = InterviewArtifact(
        tracked_job_id=job_id,
        interview_round_id=interview_round_id,
        kind=kind,
        title=effective_title[:255],
        file_url=f"/api/v1/jobs/{job_id}/artifacts/{{id}}/file",  # placeholder until we know the id
        mime_type=mime,
        content_md=content_md,
        source="uploaded",
        tags=tag_list,
    )
    db.add(art)
    await db.flush()
    # Now that we have an id, update file_url to the real streaming path.
    art.file_url = f"/api/v1/jobs/{job_id}/artifacts/{art.id}/file"
    # Stash the stored path on a JSON-ish marker inside mime_type's twin? No —
    # we don't have a spare column. Encode the filename suffix inside the URL
    # instead, and resolve from filesystem on serve. Keep it simple: we save
    # the relative path on a hidden convention derived from (user_id, stored).
    # For now, record the mapping via a deterministic filesystem path that the
    # serve endpoint reconstructs from (user_id, artifact_id) — not possible
    # without storing it. Solution: store the path suffix in file_url query.
    art.file_url = (
        f"/api/v1/jobs/{job_id}/artifacts/{art.id}/file?p={stored_name}"
    )
    await db.commit()
    await db.refresh(art)
    return art


@router.get("/{job_id:int}/artifacts/{artifact_id:int}/file")
async def download_artifact_file(
    job_id: int,
    artifact_id: int,
    p: str,
    download: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream the raw bytes of an uploaded artifact. The stored filename is
    passed via `?p=` (set by the upload endpoint); we verify it stays under
    the user's artifact directory to prevent path traversal."""
    from pathlib import Path as _Path
    from fastapi.responses import FileResponse as _FR

    art = await _get_owned_artifact(db, artifact_id, job_id, user.id)
    if art.source != "uploaded":
        raise HTTPException(
            status_code=404, detail="This artifact is not a file upload."
        )
    uploads_root = _Path("/app/uploads")
    base = uploads_root / "artifacts" / str(user.id)
    candidate = base / p
    try:
        candidate.resolve().relative_to(base.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid path.")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Backing file not found.")
    return _FR(
        path=str(candidate),
        media_type=art.mime_type or "application/octet-stream",
        filename=art.title[:120] or "artifact",
        content_disposition_type="attachment" if download else "inline",
    )


# --- JD analyzer -----------------------------------------------------------

_JD_ANALYZE_PROMPT = """You are analyzing a job description for a candidate to decide
whether to apply, and what to emphasize if they do. The user already has this
posting saved — your job is to produce a structured analysis object.

Before analyzing, you may curl the user's profile data to tailor the fit
assessment. The base URL and bearer token for the user's own data are in
environment variables JSP_API_BASE_URL and JSP_API_TOKEN. Useful endpoints:

  GET  $JSP_API_BASE_URL/api/v1/history/skills
  GET  $JSP_API_BASE_URL/api/v1/history/work
  GET  $JSP_API_BASE_URL/api/v1/history/education
  GET  $JSP_API_BASE_URL/api/v1/preferences/job         ← includes preferred_locations + remote policy
  GET  $JSP_API_BASE_URL/api/v1/preferences/authorization  ← current_location_city/region + visa

Fetch them with:

  curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" \\
       "$JSP_API_BASE_URL/api/v1/history/skills"

Keep the lookups light — two or three calls is enough.

When scoring location fit, check the posting's `location` against the user's
`preferred_locations` list. Each preferred_locations entry is
`{name, max_distance_miles}` — if the posting is within that radius (or the
posting is remote-friendly and `remote_policies_acceptable` includes the
posting's remote_policy), count it as a green flag; if the posting is onsite
and outside every preferred radius, surface it as a red_flag unless the
user's `willing_to_relocate` is true.

Here is the job description (verbatim from the posting):

---
{job_description}
---

And here is the structured metadata already extracted from the posting:

  title: {title}
  organization: {organization}
  location: {location}
  remote_policy: {remote_policy}
  salary_min: {salary_min}
  salary_max: {salary_max}
  experience_years_min: {experience_years_min}
  experience_years_max: {experience_years_max}
  experience_level: {experience_level}
  employment_type: {employment_type}
  required_skills: {required_skills}
  nice_to_have_skills: {nice_to_have_skills}

Return ONE single JSON object, no prose and no markdown fences, with this schema:

{{
  "fit_score": number,              // 0-100, rough match against user's skills/experience
  "fit_summary": string,            // 1-2 sentence plain summary of fit
  "strengths": string[],            // concrete things the user should emphasize
  "gaps": string[],                 // honest skill/experience gaps vs the JD
  "red_flags": string[],            // JD-side concerns: vague scope, toxic signals, comp mismatch, etc.
  "green_flags": string[],          // JD-side positives: clear rubric, strong comp, remote, etc.
  "interview_focus_areas": string[],// topics to prep for, based on the JD
  "suggested_questions": string[],  // questions the user should ask THEM
  "resume_emphasis": string[],      // bullets / projects from history to foreground on a tailored resume
  "cover_letter_hook": string       // one-paragraph opening hook for a cover letter
}}

All array fields should have at most 6 items. Prefer concrete examples over
generalities ("Python async with FastAPI" > "backend skills"). If any field
genuinely does not apply, return an empty array or a short "n/a" string.
"""


class JdAnalysis(BaseModel):
    fit_score: Optional[int] = None
    fit_summary: Optional[str] = None
    strengths: Optional[list[str]] = None
    gaps: Optional[list[str]] = None
    red_flags: Optional[list[str]] = None
    green_flags: Optional[list[str]] = None
    interview_focus_areas: Optional[list[str]] = None
    suggested_questions: Optional[list[str]] = None
    resume_emphasis: Optional[list[str]] = None
    cover_letter_hook: Optional[str] = None


def _build_jd_analyze_prompt(job: TrackedJob, org_name: Optional[str] = None) -> str:
    """Assemble the JD-analyzer prompt from a TrackedJob. Shared by the
    foreground request-time call and the queue worker's score handler."""
    return _JD_ANALYZE_PROMPT.format(
        job_description=job.job_description or "",
        title=job.title or "(untitled)",
        organization=org_name or "(unknown)",
        location=job.location or "(unspecified)",
        remote_policy=job.remote_policy or "(unspecified)",
        salary_min=job.salary_min if job.salary_min is not None else "null",
        salary_max=job.salary_max if job.salary_max is not None else "null",
        experience_years_min=job.experience_years_min
        if job.experience_years_min is not None
        else "null",
        experience_years_max=job.experience_years_max
        if job.experience_years_max is not None
        else "null",
        experience_level=job.experience_level or "null",
        employment_type=job.employment_type or "null",
        required_skills=", ".join(job.required_skills or []) or "(none)",
        nice_to_have_skills=", ".join(job.nice_to_have_skills or []) or "(none)",
    )


def _apply_jd_analysis_to_job(job: TrackedJob, data: dict) -> None:
    """Normalize Claude's response and persist it onto the TrackedJob. Shared
    between the single-job endpoint and the batch queue handler."""
    analysis = JdAnalysis(**{k: v for k, v in data.items() if k in JdAnalysis.model_fields})
    job.jd_analysis = analysis.model_dump()
    if analysis.fit_summary:
        job.fit_summary = {"summary": analysis.fit_summary, "score": analysis.fit_score}


async def _resolve_org_name(db: AsyncSession, org_id: Optional[int]) -> Optional[str]:
    if not org_id:
        return None
    row = (
        await db.execute(select(Organization.name).where(Organization.id == org_id))
    ).first()
    return row[0] if row else None


@router.post("/{job_id:int}/analyze-jd", response_model=TrackedJobOut)
async def analyze_jd(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrackedJob:
    """Run Claude against the saved job_description and populate
    tracked_jobs.jd_analysis. Foreground call — finishes in under 3 minutes
    for a single job. Use /batch-analyze-jd to score many at once through
    the task queue.

    Idempotent: re-running overwrites the previous analysis.
    """
    from app.core.security import create_access_token

    job = await _get_owned_job(db, job_id, user.id)
    if not (job.job_description and job.job_description.strip()):
        raise HTTPException(
            status_code=422,
            detail="No job description stored. Paste one in before analyzing.",
        )

    org_name = await _resolve_org_name(db, job.organization_id)
    prompt = _build_jd_analyze_prompt(job, org_name)

    api_token = create_access_token(
        subject=str(user.id), extra={"purpose": "jd_analyzer"}
    )

    from app.skills.queue_bus import run_claude_to_bus as _run_to_bus

    try:
        final_text = await _run_to_bus(
            prompt=prompt,
            source="jd_analyze",
            item_id=f"jd:{job_id}",
            label=f"Score: {job.title}"
            + (f" · {org_name}" if org_name else ""),
            allowed_tools=["Bash"],
            extra_env={
                "JSP_API_BASE_URL": "http://localhost:8000",
                "JSP_API_TOKEN": api_token,
            },
            timeout_seconds=180,
        )
    except ClaudeCodeError as exc:
        from app.skills.queue_worker import _is_rate_limited as _rl
        msg = str(exc)
        if _rl(msg):
            log.info("JD analyze rate-limited for job %s", job_id)
            raise HTTPException(
                status_code=429,
                detail=(
                    "Claude is rate-limited right now. Wait for your tokens "
                    "to refresh and try again, or switch to API-key billing."
                ),
            )
        log.warning("JD analyze failed for job %s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json_object(final_text) or {}
    _apply_jd_analysis_to_job(job, data)
    await db.commit()
    await db.refresh(job)
    return job


class BatchAnalyzeOut(BaseModel):
    """Shape returned by the new queue-backed batch scorer. Every un-scored
    job gets its own row on the Companion Activity page; the worker drains
    them serially with automatic rate-limit backoff."""

    enqueued: int
    skipped_no_description: int
    skipped_already_scored: int
    # Kept for frontend back-compat — these are always zero under the queue
    # model because we no longer process jobs in the request thread.
    analyzed: int = 0
    rate_limited: bool = False
    rate_limit_message: Optional[str] = None
    remaining_unprocessed: int = 0
    errors: list[dict] = []


@router.post("/batch-analyze-jd", response_model=BatchAnalyzeOut)
async def batch_analyze_jd(
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchAnalyzeOut:
    """Enqueue a JD-analysis task for every TrackedJob that has a description.

    Default: only scores jobs without a fit_score yet. `?force=1` rescores
    everything. Returns immediately with counts — the queue worker drains
    the tasks serially (to respect Claude's rate limits) and each task
    appears live on the Companion Activity page.
    """
    stmt = select(TrackedJob).where(
        TrackedJob.user_id == user.id,
        TrackedJob.deleted_at.is_(None),
    )
    jobs = list((await db.execute(stmt)).scalars().all())

    # Resolve org names once so labels read nicely.
    org_ids = [j.organization_id for j in jobs if j.organization_id]
    org_names: dict[int, str] = {}
    if org_ids:
        rows = (
            await db.execute(
                select(Organization.id, Organization.name).where(
                    Organization.id.in_(org_ids)
                )
            )
        ).all()
        org_names = {r[0]: r[1] for r in rows}

    # Don't enqueue duplicate score tasks for a job that already has one
    # pending or running — if the user spam-clicks "Score all" we shouldn't
    # stack up identical work.
    pending_rows = (
        await db.execute(
            select(JobFetchQueue.payload).where(
                JobFetchQueue.user_id == user.id,
                JobFetchQueue.kind == "score",
                JobFetchQueue.state.in_(("queued", "processing")),
            )
        )
    ).all()
    already_enqueued: set[int] = set()
    for (payload,) in pending_rows:
        if isinstance(payload, dict):
            tj = payload.get("tracked_job_id")
            if isinstance(tj, int):
                already_enqueued.add(tj)

    skipped_no_desc = 0
    skipped_scored = 0
    enqueued = 0

    for j in jobs:
        if not (j.job_description and j.job_description.strip()):
            skipped_no_desc += 1
            continue
        already_scored = (
            isinstance(j.fit_summary, dict) and j.fit_summary.get("score") is not None
        )
        if already_scored and not force:
            skipped_scored += 1
            continue
        if j.id in already_enqueued:
            # Row already has a pending score task — don't stack duplicates.
            continue

        org_name = org_names.get(j.organization_id) if j.organization_id else None
        label = f"Score: {j.title}" + (f" · {org_name}" if org_name else "")
        db.add(
            JobFetchQueue(
                user_id=user.id,
                kind="score",
                label=label[:512],
                url="",  # legacy NOT-NULL column; empty for non-fetch kinds
                payload={"tracked_job_id": j.id},
                state="queued",
            )
        )
        enqueued += 1

    await db.commit()

    return BatchAnalyzeOut(
        enqueued=enqueued,
        skipped_no_description=skipped_no_desc,
        skipped_already_scored=skipped_scored,
    )


# --- Fetch-from-URL autofill ------------------------------------------------

_FETCH_PROMPT_TEMPLATE = """Research this job posting and the hiring company. Start with the URL:

  {url}

Step 1: Use WebFetch to read the posting. Extract title, organization,
location, remote policy, salary range, the platform this was posted on, and
(if visible) the date the post was listed. For relative timestamps like
"Posted 3 days ago", compute the absolute date based on today. If no date
is visible, use null.

Step 2: Capture the FULL job description VERBATIM. This is the most important
field. Do NOT summarize, condense, paraphrase, or "clean up" — copy the
description exactly as it appears on the page, preserving bullet points,
section headers (About the role, Responsibilities, Requirements, Benefits,
etc.), and all bullet and paragraph text. Markdown formatting (##, -, **) is
fine; use it to preserve structure. Omit only page chrome (nav, cookie
banner, sidebar, related-jobs rail, apply-button text). The user will be
reviewing this description in full so completeness matters more than
brevity.

Step 3: Extract structured requirement fields from the description. Be
literal — if the JD says "5+ years" set experience_years_min=5, max=null. If
it says "3-7 years" set min=3, max=7. If it never mentions years, both null.
Experience level is a bucket the JD implies or states (junior / mid /
senior / staff / principal / manager / director / vp / cxo). Employment type
should be the JD's exact intent (full_time / part_time / contract / c2h /
internship / freelance). Education required is a bucket (none /
associates / bachelors / masters / phd) reflecting the MINIMUM required,
not "preferred". Visa sponsorship and relocation_offered are tri-state
booleans — true if explicitly offered, false if explicitly denied, null if
the JD is silent.

Step 4: Extract two skill lists from the description — required_skills
(things the JD says you must have) and nice_to_have_skills (things the JD
says are a plus, preferred, nice to have, or bonus). Use short canonical
names ("Python", "React", "Kubernetes", "GraphQL"), not full sentences.
Keep each list to at most ~15 items.

Step 5: If the company isn't a household name, use WebSearch (or WebFetch on
the company's own site) to gather a few more facts about them: website,
industry, approximate size, headquarters, a one-sentence description, and
any visible tech-stack hints. Keep that lookup light — one or two searches
is enough.

Step 6: Return ONE single JSON object with the schema below. No prose, no
markdown code fences around the JSON, no explanation before or after.
Unknown fields must be null.

Schema:
{{
  "title": string | null,
  "organization_name": string | null,
  "location": string | null,
  "remote_policy": "remote" | "hybrid" | "onsite" | null,
  "job_description": string | null,
  "salary_min": number | null,
  "salary_max": number | null,
  "salary_currency": string | null,
  "source_platform": "linkedin" | "indeed" | "company_site" | "other" | null,
  "date_posted": "YYYY-MM-DD" | null,
  "experience_years_min": number | null,
  "experience_years_max": number | null,
  "experience_level": "junior" | "mid" | "senior" | "staff" | "principal" | "manager" | "director" | "vp" | "cxo" | null,
  "employment_type": "full_time" | "part_time" | "contract" | "c2h" | "internship" | "freelance" | null,
  "education_required": "none" | "associates" | "bachelors" | "masters" | "phd" | null,
  "visa_sponsorship_offered": true | false | null,
  "relocation_offered": true | false | null,
  "required_skills": string[] | null,
  "nice_to_have_skills": string[] | null,
  "organization_website": string | null,
  "organization_industry": string | null,
  "organization_size": string | null,
  "organization_headquarters": string | null,
  "organization_description": string | null,
  "tech_stack_hints": string[] | null,
  "research_notes": string | null
}}

`organization_size` should be a bucket like "1-10", "11-50", "51-200",
"201-500", "501-1000", "1001-5000", "5001-10000", or "10000+".
`research_notes` is a one-line summary of what you looked up ("Checked
LinkedIn and the company's /about page"), NOT a summary of the job itself.
Prefer null over guesses.
"""

# Matches any JSON object inside a blob of text. Claude sometimes wraps the
# object in backticks or surrounding prose even when told not to; we yank
# the first {...} balanced-ish string out.
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json_object(text: str) -> Optional[dict]:
    """Try hard to pull a JSON object out of Claude's textual output."""
    text = text.strip()
    # First: straight json.loads.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip common markdown code fences.
    if text.startswith("```"):
        inner = "\n".join(text.splitlines()[1:])
        if inner.rstrip().endswith("```"):
            inner = inner.rsplit("```", 1)[0]
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
    # Finally: regex the first {...} blob.
    m = _JSON_OBJECT_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


async def perform_fetch(
    db: AsyncSession,
    url: str,
    *,
    on_event: "Optional[callable]" = None,
) -> FetchedJobInfo:
    """Core URL-fetch + org-enrichment pipeline.

    When `on_event` is provided, uses the streaming Claude Code variant and
    invokes the callback for each captured event (text chunk, tool_use,
    result summary). Used by the queue worker to pipe live output to the
    in-memory pub/sub. When None, runs the cheaper single-shot JSON mode.

    Raises ClaudeCodeError on CLI failure; otherwise the FetchedJobInfo has
    organization_id set when an org was resolved or created.
    """
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("URL must start with http(s)://")

    prompt = _FETCH_PROMPT_TEMPLATE.format(url=url)

    final_text = ""
    if on_event is not None:
        from datetime import datetime as _dt, timezone as _tz
        from app.skills.runner import (
            ClaudeCodeError as _CCE,
            stream_claude_prompt as _scp,
        )
        collected: list[str] = []
        had_error: str | None = None

        def _emit(ev: dict) -> None:
            ev["t"] = _dt.now(tz=_tz.utc).isoformat(timespec="seconds")
            try:
                on_event(ev)
            except Exception:  # pragma: no cover  (bus error must not kill fetch)
                pass

        async for raw in _scp(
            prompt=prompt,
            allowed_tools=["WebFetch", "WebSearch"],
            timeout_seconds=240,
        ):
            ev_type = raw.get("type")
            if ev_type == "system":
                _emit({"kind": "system", "text": "Claude session started"})
            elif ev_type == "error":
                had_error = str(raw.get("message") or "streaming error")
                _emit({"kind": "error", "text": had_error})
            elif ev_type == "assistant":
                msg = raw.get("message") or {}
                for block in (msg.get("content") or []):
                    btype = (block or {}).get("type")
                    if btype == "text":
                        text = block.get("text") or ""
                        if text.strip():
                            collected.append(text)
                            _emit({"kind": "text", "text": text})
                    elif btype == "tool_use":
                        inp = block.get("input") or {}
                        compact = {
                            k: (
                                (str(v)[:300] + "…")
                                if isinstance(v, str) and len(str(v)) > 300
                                else v
                            )
                            for k, v in inp.items()
                        }
                        _emit(
                            {
                                "kind": "tool_use",
                                "tool": block.get("name"),
                                "input": compact,
                            }
                        )
            elif ev_type == "stream_event":
                continue
            elif ev_type == "result":
                if not collected and raw.get("result"):
                    collected.append(str(raw["result"]))
                _emit(
                    {
                        "kind": "result",
                        "cost_usd": raw.get("total_cost_usd") or raw.get("cost_usd"),
                        "duration_ms": raw.get("duration_ms"),
                        "num_turns": raw.get("num_turns"),
                    }
                )
        final_text = "".join(collected)
        if had_error and not final_text:
            raise _CCE(had_error)
    else:
        result = await run_claude_prompt(
            prompt=prompt,
            output_format="json",
            allowed_tools=["WebFetch", "WebSearch"],
            timeout_seconds=180,
        )
        final_text = result.result

    data = _extract_json_object(final_text) or {}
    if data.get("remote_policy") not in (None, "remote", "hybrid", "onsite"):
        data["remote_policy"] = None
    if data.get("source_platform") not in (
        None,
        "linkedin",
        "indeed",
        "company_site",
        "other",
    ):
        data["source_platform"] = None

    out = FetchedJobInfo(
        **{k: v for k, v in data.items() if k in FetchedJobInfo.model_fields},
        source_url=url,
    )

    if out.organization_name:
        org = (
            await db.execute(
                select(Organization).where(
                    func.lower(Organization.name) == out.organization_name.strip().lower(),
                    Organization.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if org is None:
            org = Organization(name=out.organization_name.strip(), type="company")
            db.add(org)
            await db.flush()

        enrichment_map = {
            "website": out.organization_website,
            "industry": out.organization_industry,
            "size": out.organization_size,
            "headquarters_location": out.organization_headquarters,
            "description": out.organization_description,
        }
        for attr, value in enrichment_map.items():
            if value and not getattr(org, attr, None):
                setattr(org, attr, value)
        if out.research_notes and not org.research_notes:
            org.research_notes = out.research_notes
        if out.tech_stack_hints:
            existing = list(org.tech_stack_hints or [])
            org.tech_stack_hints = existing + [
                h for h in out.tech_stack_hints if h not in existing
            ]

        await db.commit()
        out.organization_id = org.id

    if not any(
        [out.title, out.organization_name, out.job_description, out.location]
    ):
        out.warning = (
            "Couldn't extract recognizable job info from that URL. "
            "The page may require sign-in, be JavaScript-only, or not be a job posting."
        )

    return out


def build_tracked_job_payload(
    fetched: FetchedJobInfo, overrides: Optional[dict] = None
) -> dict:
    """Build a TrackedJob field dict from a FetchedJobInfo plus optional
    user-supplied overrides (status, priority, date_applied, etc.)."""
    payload = {
        "title": fetched.title or "(untitled)",
        "organization_id": fetched.organization_id,
        "job_description": fetched.job_description,
        "source_url": fetched.source_url,
        "source_platform": fetched.source_platform,
        "location": fetched.location,
        "remote_policy": fetched.remote_policy,
        "salary_min": fetched.salary_min,
        "salary_max": fetched.salary_max,
        "salary_currency": fetched.salary_currency,
        "date_posted": fetched.date_posted,
        "experience_years_min": fetched.experience_years_min,
        "experience_years_max": fetched.experience_years_max,
        "experience_level": fetched.experience_level,
        "employment_type": fetched.employment_type,
        "education_required": fetched.education_required,
        "visa_sponsorship_offered": fetched.visa_sponsorship_offered,
        "relocation_offered": fetched.relocation_offered,
        "required_skills": fetched.required_skills,
        "nice_to_have_skills": fetched.nice_to_have_skills,
    }
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                payload[k] = v
    return payload


@router.post("/fetch-from-url", response_model=FetchedJobInfo)
async def fetch_from_url(
    body: FetchFromUrlIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FetchedJobInfo:
    """Invoke Claude Code's WebFetch to pull structured job info from a URL.

    Does NOT create a TrackedJob — the frontend uses this to prefill the
    New Job form. The user can review and edit before saving.
    """
    try:
        return await perform_fetch(db, body.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ClaudeCodeError as exc:
        log.warning("URL fetch failed for %s: %s", body.url, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")


# --- JobFetchQueue ----------------------------------------------------------


@router.get("/queue/stream")
async def stream_queue_activity(
    _: User = Depends(get_current_user),
):
    """Server-Sent-Events feed of live queue-worker activity.

    Not persisted — each connected client just sees whatever the worker is
    doing from the moment they subscribe. Events include:

      {kind: "start", item_id, url}
      {kind: "system", item_id, url, text}
      {kind: "text", item_id, url, text}       — Claude's prose
      {kind: "tool_use", item_id, url, tool, input}
      {kind: "result", item_id, url, cost_usd, duration_ms, num_turns}
      {kind: "done", item_id, url, created_tracked_job_id}
      {kind: "error", item_id, url, text}

    A periodic `: keepalive` comment keeps the connection warm through
    proxies that drop idle streams.
    """
    import asyncio as _a
    import json as _json

    from fastapi.responses import StreamingResponse
    from app.skills import queue_bus as _bus

    q = _bus.subscribe()

    async def gen():
        try:
            yield f'data: {_json.dumps({"kind": "subscribed"})}\n\n'.encode("utf-8")
            while True:
                try:
                    ev = await _a.wait_for(q.get(), timeout=15.0)
                    yield f"data: {_json.dumps(ev)}\n\n".encode("utf-8")
                except _a.TimeoutError:
                    yield b": keepalive\n\n"
        finally:
            _bus.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/queue", response_model=list[JobFetchQueueOut])
async def list_queue(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[JobFetchQueue]:
    stmt = (
        select(JobFetchQueue)
        .where(JobFetchQueue.user_id == user.id)
        .order_by(JobFetchQueue.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


class ActivityRowOut(BaseModel):
    """Unified row shape covering both persistent fetch-queue items and
    in-memory Companion task-registry rows. The Companion Activity page
    renders one list mixing both."""

    # Stable id unique across kinds. "fetch:<id>" or "task:<source>:<item_id>".
    id: str
    kind: str                       # "fetch" | "companion"
    source: str                     # "fetch", "tailor_resume", etc.
    label: str                      # url (fetch) or task label (companion)
    status: str                     # queued | processing | running | done | error
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_text: Optional[str] = None
    last_tool: Optional[str] = None
    error: Optional[str] = None
    # Fetch-specific
    fetch_queue_id: Optional[int] = None
    url: Optional[str] = None
    attempts: Optional[int] = None
    resume_after: Optional[datetime] = None
    tracked_job_id: Optional[int] = None
    # Companion-task-specific
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    num_turns: Optional[int] = None


def _companion_task_to_row(task: dict) -> ActivityRowOut:
    def _parse_iso(v):
        if not v:
            return None
        try:
            return datetime.fromisoformat(v)
        except Exception:
            return None

    return ActivityRowOut(
        id=f"task:{task['key']}",
        kind="companion",
        source=task["source"],
        label=task.get("label") or task["source"],
        status=task.get("status") or "running",
        started_at=_parse_iso(task.get("started_at")),
        updated_at=_parse_iso(task.get("updated_at")),
        finished_at=_parse_iso(task.get("finished_at")),
        last_text=task.get("last_text"),
        last_tool=task.get("last_tool"),
        error=task.get("error"),
        cost_usd=task.get("cost_usd"),
        duration_ms=task.get("duration_ms"),
        num_turns=task.get("num_turns"),
    )


def _fetch_queue_to_row(item: JobFetchQueue) -> ActivityRowOut:
    # Post-migration-0012, `kind` discriminates between fetch / score /
    # tailor / humanize / ... — older rows carry NULL and mean fetch.
    kind = item.kind or "fetch"
    # Human label per kind, defaulting to whatever was stored on the row
    # (the enqueuer sets `label` most of the time).
    if item.label:
        label = item.label
    elif kind == "fetch":
        label = item.url or "(no url)"
    elif isinstance(item.payload, dict) and item.payload.get("tracked_job_id"):
        label = f"{kind}: job #{item.payload['tracked_job_id']}"
    else:
        label = f"{kind} #{item.id}"
    # For non-fetch kinds, surface the tracked_job_id from the payload so
    # the UI can still deep-link the row. Fetch rows already expose it via
    # `created_tracked_job_id`.
    related_tracked_job_id = item.created_tracked_job_id
    if related_tracked_job_id is None and isinstance(item.payload, dict):
        tj = item.payload.get("tracked_job_id")
        if isinstance(tj, int):
            related_tracked_job_id = tj

    # Merge live progress from the in-memory bus registry, if any. Worker
    # handlers publish with item_id=f"queue:{row.id}", so a single lookup
    # covers every kind. Source names differ per kind (e.g. kind="score"
    # publishes as source="jd_analyze"), so try a few candidates.
    from app.skills import queue_bus as _bus
    _SOURCE_FOR_KIND = {
        "fetch": "fetch",
        "score": "jd_analyze",
    }
    bus_source = _SOURCE_FOR_KIND.get(kind, kind)
    task = _bus.get_task(bus_source, f"queue:{item.id}")
    last_text = task.get("last_text") if task else None
    last_tool = task.get("last_tool") if task else None
    cost_usd = task.get("cost_usd") if task else None
    duration_ms = task.get("duration_ms") if task else None
    num_turns = task.get("num_turns") if task else None

    return ActivityRowOut(
        id=f"fetch:{item.id}",  # stable id across kinds — table is shared
        kind="fetch" if kind == "fetch" else "companion",
        source=kind,
        label=label,
        status=item.state or "queued",
        started_at=item.last_attempt_at,
        updated_at=item.last_attempt_at or item.created_at,
        finished_at=None,
        last_text=last_text,
        last_tool=last_tool,
        error=item.error_message,
        fetch_queue_id=item.id,
        url=item.url if kind == "fetch" else None,
        attempts=item.attempts,
        resume_after=item.resume_after,
        tracked_job_id=related_tracked_job_id,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        num_turns=num_turns,
    )


@router.get("/activity", response_model=list[ActivityRowOut])
async def list_activity(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ActivityRowOut]:
    """Unified Companion Activity feed: fetch-queue items + every in-flight
    / recent task from the Claude bus (tailor, humanize, score, research,
    chat, etc.). Sorted by updated_at descending so the most recently
    active rows float to the top.
    """
    from app.skills import queue_bus as _bus

    fetch_stmt = (
        select(JobFetchQueue)
        .where(JobFetchQueue.user_id == user.id)
        .order_by(JobFetchQueue.id.desc())
    )
    fetch_rows = [
        _fetch_queue_to_row(i)
        for i in (await db.execute(fetch_stmt)).scalars().all()
    ]

    # Non-fetch DB rows are also in the bus task registry (the worker
    # publishes while running). Skip any bus entry whose item_id points at
    # a DB row — the DB row is the canonical representation and already
    # carries progress data (merged in `_fetch_queue_to_row`).
    task_rows: list[ActivityRowOut] = []
    for t in _bus.list_tasks(limit=200):
        item_id = str(t.get("item_id") or "")
        if item_id.startswith("queue:"):
            continue
        task_rows.append(_companion_task_to_row(t))

    merged = fetch_rows + task_rows
    # JobFetchQueue datetimes come back naive from MySQL; companion-task rows
    # are tz-aware ISO strings. Normalize both so we can mix them in a sort.
    _min = datetime.min.replace(tzinfo=timezone.utc)

    def _sort_key(r: ActivityRowOut) -> datetime:
        d = r.updated_at or r.started_at
        if d is None:
            return _min
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    merged.sort(key=_sort_key, reverse=True)
    return merged


@router.get("/activity/stream")
async def stream_activity_tasks(
    _: User = Depends(get_current_user),
):
    """SSE stream of task-registry row updates. Each event is one row's
    current state (the frontend replaces by id). A separate, lighter-weight
    stream than `/queue/stream` — use this to keep the unified activity
    list live without having to reason about raw text deltas."""
    import asyncio as _a
    import json as _json

    from fastapi.responses import StreamingResponse
    from app.skills import queue_bus as _bus

    q = _bus.subscribe_tasks()

    async def gen():
        try:
            yield f'data: {_json.dumps({"kind": "subscribed"})}\n\n'.encode("utf-8")
            # Prime with current snapshot so a fresh client gets the full list
            # without waiting for the next event.
            for t in _bus.list_tasks(limit=200):
                payload = {"kind": "task_update", **t}
                yield f"data: {_json.dumps(payload)}\n\n".encode("utf-8")
            while True:
                try:
                    ev = await _a.wait_for(q.get(), timeout=15.0)
                    yield f"data: {_json.dumps(ev)}\n\n".encode("utf-8")
                except _a.TimeoutError:
                    yield b": keepalive\n\n"
        finally:
            _bus.unsubscribe_tasks(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/queue",
    response_model=JobFetchQueueOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def enqueue_url(
    payload: JobFetchQueueIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobFetchQueue:
    url = payload.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=422, detail="URL must start with http(s)://")
    if payload.desired_status is not None:
        _validate_status(payload.desired_status)
    if payload.desired_priority:
        _validate_simple(payload.desired_priority, PRIORITIES, "priority")

    item = JobFetchQueue(
        user_id=user.id,
        url=url,
        kind="fetch",
        label=url[:512],
        desired_status=payload.desired_status,
        desired_priority=payload.desired_priority,
        desired_date_applied=payload.desired_date_applied,
        desired_date_closed=payload.desired_date_closed,
        desired_notes=payload.desired_notes,
        state="queued",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/queue/{item_id:int}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_queue_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    stmt = select(JobFetchQueue).where(
        JobFetchQueue.id == item_id, JobFetchQueue.user_id == user.id
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    await db.delete(item)
    await db.commit()


# --- Excel bulk import ------------------------------------------------------


@router.get("/import-template.xlsx")
async def download_import_template(_: User = Depends(get_current_user)) -> Response:
    """Serve a pre-formatted .xlsx template for bulk-importing TrackedJobs."""
    from app.skills.excel_io import build_template_workbook

    data = build_template_workbook()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="job-search-pal-template.xlsx"',
            "Content-Length": str(len(data)),
        },
    )


@router.post("/import")
async def import_jobs_from_xlsx(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Accept an .xlsx matching the import template and create TrackedJobs
    for each non-empty row. Returns created/skipped counts and any per-row
    errors so the user can fix and re-upload.
    """
    from app.skills.excel_io import parse_workbook

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    try:
        rows = parse_workbook(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    created: list[int] = []
    errors: list[dict] = []

    for row_num, row in enumerate(rows, start=2):
        title = row.get("title")
        if not title:
            errors.append({"row": row_num, "error": "Title is required"})
            continue

        status_val = row.get("status")
        if status_val and status_val not in JOB_STATUSES:
            errors.append(
                {"row": row_num, "error": f"Unknown status '{status_val}'"}
            )
            continue

        # Resolve / create Organization by name (case-insensitive).
        org_id: Optional[int] = None
        org_name = row.pop("organization_name", None)
        if org_name:
            org = (
                await db.execute(
                    select(Organization).where(
                        func.lower(Organization.name) == org_name.strip().lower(),
                        Organization.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if org is None:
                org = Organization(name=org_name.strip(), type="company")
                db.add(org)
                await db.flush()
            org_id = org.id

        payload: dict = {"user_id": user.id, "organization_id": org_id}
        for k, v in row.items():
            if v is not None:
                payload[k] = v
        payload.setdefault("status", "watching")
        payload.setdefault("date_discovered", date.today())

        try:
            job = TrackedJob(**payload)
            db.add(job)
            await db.flush()
            db.add(
                ApplicationEvent(
                    tracked_job_id=job.id,
                    event_type="note",
                    event_date=datetime.now(tz=timezone.utc),
                    details_md=f"Imported from Excel with status `{job.status}`.",
                )
            )
            created.append(job.id)
        except Exception as exc:
            errors.append({"row": row_num, "error": str(exc)})

    await db.commit()
    return {
        "created": created,
        "created_count": len(created),
        "skipped_count": len(errors),
        "errors": errors,
    }


@router.get("/queue-import-template.xlsx")
async def download_queue_import_template(
    _: User = Depends(get_current_user),
) -> Response:
    """Serve a minimal .xlsx template for queue bulk-import: URL + optional
    applied/posted dates. Rows get pushed to the fetch queue, not created
    directly as TrackedJobs."""
    from app.skills.excel_io import build_queue_template_workbook

    data = build_queue_template_workbook()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="job-search-pal-queue-template.xlsx"',
            "Content-Length": str(len(data)),
        },
    )


@router.post("/queue-import")
async def import_queue_from_xlsx(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Accept an .xlsx matching the queue-import template and enqueue each
    row in the fetch queue. Returns enqueued/skipped counts plus per-row
    errors for malformed URLs."""
    from app.skills.excel_io import parse_queue_workbook

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    try:
        rows = parse_queue_workbook(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    enqueued: list[int] = []
    errors: list[dict] = []

    for row_num, row in enumerate(rows, start=2):
        url = row.get("url")
        if not url or not isinstance(url, str):
            errors.append({"row": row_num, "error": "Job URL is required"})
            continue
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            errors.append(
                {"row": row_num, "error": f"Unrecognized URL: {url[:120]}"}
            )
            continue

        item = JobFetchQueue(
            user_id=user.id,
            url=url,
            desired_date_applied=row.get("desired_date_applied"),
            desired_date_posted=row.get("desired_date_posted"),
            state="queued",
            attempts=0,
        )
        db.add(item)
        try:
            await db.flush()
            enqueued.append(item.id)
        except Exception as exc:
            errors.append({"row": row_num, "error": str(exc)})

    await db.commit()
    return {
        "enqueued": enqueued,
        "enqueued_count": len(enqueued),
        "skipped_count": len(errors),
        "errors": errors,
    }


@router.post("/queue/{item_id:int}/retry", response_model=JobFetchQueueOut)
async def retry_queue_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobFetchQueue:
    stmt = select(JobFetchQueue).where(
        JobFetchQueue.id == item_id, JobFetchQueue.user_id == user.id
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    if item.state == "processing":
        raise HTTPException(status_code=409, detail="Already processing")
    item.state = "queued"
    item.error_message = None
    item.attempts = 0
    await db.commit()
    await db.refresh(item)
    return item
