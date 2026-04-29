"""Preferences & Identity: JobPreferences, JobCriterion, WorkAuthorization,
Demographics.

All singleton-per-user (except JobCriterion which is a list). The endpoints
use simple upsert semantics — a PUT replaces the record's fields. Keeping
this minimal so the frontend can drive a single scroll-form per panel
rather than granular PATCHes.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.preferences import (
    Demographics,
    JobCriterion,
    JobPreferences,
    ResumeProfile,
    WorkAuthorization,
)
from app.models.user import User

router = APIRouter(prefix="/preferences", tags=["preferences"])


# --- JobPreferences ---------------------------------------------------------


class PreferredLocationIn(BaseModel):
    """One entry on JobPreferences.preferred_locations."""

    name: str = Field(min_length=1, max_length=255)
    # None = "no cap — anywhere near this place" (the user just wants to
    # flag that they'd like working from here, open to commute).
    max_distance_miles: Optional[int] = Field(default=None, ge=0, le=2000)


class JobPreferencesIn(BaseModel):
    salary_currency: str = "USD"
    salary_preferred_target: Optional[float] = None
    salary_acceptable_min: Optional[float] = None
    salary_unacceptable_below: Optional[float] = None
    total_comp_preferred_target: Optional[float] = None
    total_comp_acceptable_min: Optional[float] = None
    experience_level_preferred: Optional[str] = None
    experience_levels_acceptable: Optional[list[str]] = None
    experience_levels_unacceptable: Optional[list[str]] = None
    remote_policy_preferred: Optional[str] = None
    remote_policies_acceptable: Optional[list[str]] = None
    remote_policies_unacceptable: Optional[list[str]] = None
    max_commute_minutes_preferred: Optional[int] = None
    max_commute_minutes_acceptable: Optional[int] = None
    willing_to_relocate: bool = False
    relocation_notes: Optional[str] = None
    # Preferred target locations, each with a miles radius. Validated
    # loosely — we accept any list of `{name, max_distance_miles}` dicts
    # (miles may be None for "anywhere in / near this place").
    preferred_locations: Optional[list[PreferredLocationIn]] = None
    travel_percent_preferred: Optional[int] = None
    travel_percent_acceptable_max: Optional[int] = None
    travel_percent_unacceptable_above: Optional[int] = None
    hours_per_week_preferred: Optional[int] = None
    hours_per_week_acceptable_max: Optional[int] = None
    overtime_acceptable: bool = False
    schedule_preferred: Optional[str] = None
    schedules_acceptable: Optional[list[str]] = None
    schedules_unacceptable: Optional[list[str]] = None
    employment_types_preferred: Optional[list[str]] = None
    employment_types_acceptable: Optional[list[str]] = None
    employment_types_unacceptable: Optional[list[str]] = None
    equity_preference: Optional[str] = None
    benefits_required: Optional[list[str]] = None
    benefits_preferred: Optional[list[str]] = None
    earliest_start_date: Optional[date] = None
    latest_start_date: Optional[date] = None
    notice_period_weeks: Optional[int] = None
    dealbreakers_notes: Optional[str] = None
    dream_job_notes: Optional[str] = None
    # Per-user weight overrides for the deterministic fit-score's
    # built-in components. Keys: salary, remote_policy, location,
    # experience_level, employment_type, travel, hours. Values 0-100.
    # Unset keys fall back to DEFAULT_BUILTIN_WEIGHTS in app/scoring/fit.py.
    builtin_weights: Optional[dict[str, int]] = None


class JobPreferencesOut(JobPreferencesIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


@router.get("/job", response_model=Optional[JobPreferencesOut])
async def get_job_preferences(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Optional[JobPreferences]:
    stmt = select(JobPreferences).where(
        JobPreferences.user_id == user.id,
        JobPreferences.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.put("/job", response_model=JobPreferencesOut)
async def upsert_job_preferences(
    payload: JobPreferencesIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobPreferences:
    existing = (
        await db.execute(
            select(JobPreferences).where(
                JobPreferences.user_id == user.id,
                JobPreferences.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    data = payload.model_dump()
    if existing is None:
        existing = JobPreferences(user_id=user.id, **data)
        db.add(existing)
    else:
        for k, v in data.items():
            setattr(existing, k, v)
    await db.commit()
    await db.refresh(existing)
    return existing


# --- WorkAuthorization ------------------------------------------------------


class WorkAuthorizationIn(BaseModel):
    current_country: Optional[str] = None
    current_location_city: Optional[str] = None
    current_location_region: Optional[str] = None
    citizenship_countries: Optional[list[str]] = None
    work_authorization_status: Optional[str] = None
    visa_type: Optional[str] = None
    visa_issued_date: Optional[date] = None
    visa_expires_date: Optional[date] = None
    visa_sponsorship_required_now: bool = False
    visa_sponsorship_required_future: bool = False
    relocation_countries_acceptable: Optional[list[str]] = None
    security_clearance_level: Optional[str] = None
    security_clearance_active: bool = False
    security_clearance_notes: Optional[str] = None
    export_control_considerations: Optional[str] = None


class WorkAuthorizationOut(WorkAuthorizationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


@router.get("/authorization", response_model=Optional[WorkAuthorizationOut])
async def get_work_authorization(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Optional[WorkAuthorization]:
    return (
        await db.execute(
            select(WorkAuthorization).where(
                WorkAuthorization.user_id == user.id,
                WorkAuthorization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


@router.put("/authorization", response_model=WorkAuthorizationOut)
async def upsert_work_authorization(
    payload: WorkAuthorizationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkAuthorization:
    existing = (
        await db.execute(
            select(WorkAuthorization).where(
                WorkAuthorization.user_id == user.id,
                WorkAuthorization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    data = payload.model_dump()
    if existing is None:
        existing = WorkAuthorization(user_id=user.id, **data)
        db.add(existing)
    else:
        for k, v in data.items():
            setattr(existing, k, v)
    await db.commit()
    await db.refresh(existing)
    return existing


# --- Demographics -----------------------------------------------------------


class DemographicsIn(BaseModel):
    preferred_name: Optional[str] = None
    legal_first_name: Optional[str] = None
    legal_middle_name: Optional[str] = None
    legal_last_name: Optional[str] = None
    legal_suffix: Optional[str] = None
    pronouns: Optional[str] = None
    pronouns_self_describe: Optional[str] = None
    gender_identity: Optional[str] = None
    gender_self_describe: Optional[str] = None
    sex_assigned_at_birth: Optional[str] = None
    transgender_identification: Optional[str] = None
    sexual_orientation: Optional[str] = None
    sexual_orientation_self_describe: Optional[str] = None
    race_ethnicity: Optional[list[str]] = None
    ethnicity_self_describe: Optional[str] = None
    veteran_status: Optional[str] = None
    disability_status: Optional[str] = None
    disability_notes: Optional[str] = None
    accommodation_needs: Optional[str] = None
    date_of_birth: Optional[date] = None
    age_bracket: Optional[str] = None
    first_generation_college_student: Optional[str] = None


class DemographicsOut(DemographicsIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


@router.get("/demographics", response_model=Optional[DemographicsOut])
async def get_demographics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Optional[Demographics]:
    return (
        await db.execute(
            select(Demographics).where(
                Demographics.user_id == user.id,
                Demographics.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


@router.put("/demographics", response_model=DemographicsOut)
async def upsert_demographics(
    payload: DemographicsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Demographics:
    existing = (
        await db.execute(
            select(Demographics).where(
                Demographics.user_id == user.id,
                Demographics.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    data = payload.model_dump()
    if existing is None:
        existing = Demographics(user_id=user.id, **data)
        db.add(existing)
    else:
        for k, v in data.items():
            setattr(existing, k, v)
    await db.commit()
    await db.refresh(existing)
    return existing


# --- ResumeProfile ----------------------------------------------------------


class ResumeLinkIn(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=1, max_length=1024)


class ResumeProfileIn(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    headline: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=64)
    location: Optional[str] = Field(default=None, max_length=255)
    linkedin_url: Optional[str] = Field(default=None, max_length=1024)
    github_url: Optional[str] = Field(default=None, max_length=1024)
    portfolio_url: Optional[str] = Field(default=None, max_length=1024)
    website_url: Optional[str] = Field(default=None, max_length=1024)
    other_links: Optional[list[ResumeLinkIn]] = None
    professional_summary: Optional[str] = None


class ResumeProfileOut(ResumeProfileIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


@router.get("/resume-profile", response_model=Optional[ResumeProfileOut])
async def get_resume_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Optional[ResumeProfile]:
    return (
        await db.execute(
            select(ResumeProfile).where(
                ResumeProfile.user_id == user.id,
                ResumeProfile.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


@router.put("/resume-profile", response_model=ResumeProfileOut)
async def upsert_resume_profile(
    payload: ResumeProfileIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResumeProfile:
    existing = (
        await db.execute(
            select(ResumeProfile).where(
                ResumeProfile.user_id == user.id,
                ResumeProfile.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    data = payload.model_dump()
    # Normalize other_links into plain dicts (list[ResumeLinkIn] → list[dict]).
    if data.get("other_links") is not None:
        data["other_links"] = [
            {"label": x["label"], "url": x["url"]} for x in data["other_links"]
        ]
    if existing is None:
        existing = ResumeProfile(user_id=user.id, **data)
        db.add(existing)
    else:
        for k, v in data.items():
            setattr(existing, k, v)
    await db.commit()
    await db.refresh(existing)
    return existing


# --- JobCriterion list ------------------------------------------------------


class JobCriterionIn(BaseModel):
    category: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=255)
    tier: str = Field(default="preferred")  # preferred / acceptable / unacceptable
    # 0-100. The deterministic fit-score reads this directly:
    # 0 = informational only (excluded from numerator + denominator).
    # 100 + tier=unacceptable + matched JD = hard veto (score = 0).
    weight: Optional[int] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None


class JobCriterionOut(JobCriterionIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


@router.get("/criteria", response_model=list[JobCriterionOut])
async def list_criteria(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[JobCriterion]:
    stmt = (
        select(JobCriterion)
        .where(
            JobCriterion.user_id == user.id,
            JobCriterion.deleted_at.is_(None),
        )
        .order_by(JobCriterion.category.asc(), JobCriterion.tier.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("/criteria", response_model=JobCriterionOut, status_code=status.HTTP_201_CREATED)
async def create_criterion(
    payload: JobCriterionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobCriterion:
    if payload.tier not in {"preferred", "acceptable", "unacceptable"}:
        raise HTTPException(
            status_code=422,
            detail="tier must be preferred / acceptable / unacceptable",
        )

    # Upsert semantics: `uq_job_criterion` covers (user_id, category, value)
    # *including* soft-deleted rows — MySQL doesn't do partial-unique
    # indexes. So if this exact tuple exists (live or previously deleted),
    # overwrite its tier/weight/notes and clear `deleted_at` instead of
    # inserting a collision.
    existing = (
        await db.execute(
            select(JobCriterion).where(
                JobCriterion.user_id == user.id,
                JobCriterion.category == payload.category,
                JobCriterion.value == payload.value,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        data = payload.model_dump()
        for k, v in data.items():
            setattr(existing, k, v)
        existing.deleted_at = None
        await db.commit()
        await db.refresh(existing)
        return existing

    c = JobCriterion(user_id=user.id, **payload.model_dump())
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@router.put("/criteria/{criterion_id:int}", response_model=JobCriterionOut)
async def update_criterion(
    criterion_id: int,
    payload: JobCriterionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobCriterion:
    c = (
        await db.execute(
            select(JobCriterion).where(
                JobCriterion.id == criterion_id,
                JobCriterion.user_id == user.id,
                JobCriterion.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Criterion not found")
    if payload.tier not in {"preferred", "acceptable", "unacceptable"}:
        raise HTTPException(
            status_code=422,
            detail="tier must be preferred / acceptable / unacceptable",
        )
    for k, v in payload.model_dump().items():
        setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return c


@router.delete("/criteria/{criterion_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_criterion(
    criterion_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    c = (
        await db.execute(
            select(JobCriterion).where(
                JobCriterion.id == criterion_id,
                JobCriterion.user_id == user.id,
                JobCriterion.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Criterion not found")
    c.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()
