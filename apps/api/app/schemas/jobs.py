"""Pydantic models for TrackedJob, ApplicationEvent, and InterviewRound."""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# Canonical status vocabulary. Kept loose (string) on the ORM so we can add
# values without a migration, but validated here.
JOB_STATUSES = {
    "watching",
    "interested",
    "applied",
    "responded",
    "screening",
    "interviewing",
    "assessment",
    "offer",
    "won",
    "lost",
    "withdrawn",
    "ghosted",
    "archived",
}

REMOTE_POLICIES = {"onsite", "hybrid", "remote"}
PRIORITIES = {"low", "medium", "high"}


# --------- TrackedJob --------------------------------------------------------

class _TrackedJobCommon(BaseModel):
    organization_id: Optional[int] = None
    job_description: Optional[str] = None
    source_url: Optional[str] = None
    source_platform: Optional[str] = None
    location: Optional[str] = None
    remote_policy: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    equity_notes: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    date_posted: Optional[date] = None
    date_discovered: Optional[date] = None
    date_applied: Optional[date] = None
    date_closed: Optional[date] = None
    # JD-extracted fields
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None
    experience_level: Optional[str] = None
    employment_type: Optional[str] = None
    education_required: Optional[str] = None
    visa_sponsorship_offered: Optional[bool] = None
    relocation_offered: Optional[bool] = None
    required_skills: Optional[list[str]] = None
    nice_to_have_skills: Optional[list[str]] = None


class TrackedJobIn(_TrackedJobCommon):
    title: str = Field(min_length=1, max_length=255)


class TrackedJobUpdate(_TrackedJobCommon):
    """All fields optional — PATCH-style, used by the PUT endpoint."""

    title: Optional[str] = Field(default=None, max_length=255)


class TrackedJobOut(TrackedJobIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    organization_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    jd_analysis: Optional[Any] = None
    fit_summary: Optional[Any] = None


class TrackedJobSummary(BaseModel):
    """Lightweight shape for the tracker list view."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    status: str
    priority: Optional[str] = None
    remote_policy: Optional[str] = None
    location: Optional[str] = None
    organization_id: Optional[int] = None
    organization_name: Optional[str] = None
    date_applied: Optional[date] = None
    date_discovered: Optional[date] = None
    updated_at: datetime
    rounds_count: int = 0
    latest_round_outcome: Optional[str] = None
    # Summary-only highlights for the table view.
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    experience_level: Optional[str] = None
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None
    employment_type: Optional[str] = None
    # Populated by the JD analyzer — surfaced on the tracker list for quick triage.
    fit_score: Optional[int] = None
    # Count of red-flag items from jd_analysis.red_flags. Tracker row flags a
    # warning icon when > 0.
    red_flag_count: int = 0


# --------- InterviewRound ----------------------------------------------------

class InterviewRoundIn(BaseModel):
    round_number: int = 1
    round_type: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    format: Optional[str] = None
    location_or_link: Optional[str] = None
    interviewers: Optional[list[dict]] = None
    outcome: Optional[str] = None  # pending / passed / failed / mixed / unknown
    self_rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes_md: Optional[str] = None
    prep_notes_md: Optional[str] = None


class InterviewRoundOut(InterviewRoundIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tracked_job_id: int
    outcome: str
    created_at: datetime
    updated_at: datetime


# --------- InterviewArtifact ------------------------------------------------

ARTIFACT_KINDS = {
    "take_home",
    "whiteboard_capture",
    "notes",
    "feedback",
    "offer_letter",
    "recruiter_email",
    "prep_doc",
    "other",
}


class InterviewArtifactIn(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=255)
    interview_round_id: Optional[int] = None
    file_url: Optional[str] = None
    mime_type: Optional[str] = None
    content_md: Optional[str] = None
    source: Optional[str] = None  # uploaded / generated / pasted / other
    tags: Optional[list[str]] = None


class InterviewArtifactOut(InterviewArtifactIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tracked_job_id: int
    created_at: datetime
    updated_at: datetime


# --------- ApplicationEvent --------------------------------------------------

class ApplicationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tracked_job_id: int
    event_type: str
    event_date: datetime
    details_md: Optional[str] = None
    related_round_id: Optional[int] = None
    created_at: datetime


class ApplicationEventIn(BaseModel):
    event_type: str
    event_date: Optional[datetime] = None  # defaults to now server-side
    details_md: Optional[str] = None
    related_round_id: Optional[int] = None


# --------- JobFetchQueue ----------------------------------------------------

QUEUE_STATES = {"queued", "processing", "done", "error"}


class JobFetchQueueIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    desired_status: Optional[str] = None
    desired_priority: Optional[str] = None
    desired_date_applied: Optional[date] = None
    desired_date_closed: Optional[date] = None
    desired_date_posted: Optional[date] = None
    desired_notes: Optional[str] = None


class JobFetchQueueOut(JobFetchQueueIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    state: str
    attempts: int
    last_attempt_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_tracked_job_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# --------- URL fetch / autofill ---------------------------------------------

class FetchFromUrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class FetchedJobInfo(BaseModel):
    """Best-effort extracted job posting and enriched org context.

    All fields optional — the UI treats `null` as "couldn't determine" and
    leaves the form empty for that field. Enriched org-level fields come
    from WebSearch / WebFetch calls Claude chose to make beyond the posting
    URL itself, and are written back onto the matched/created Organization
    record in fields the user hasn't already populated."""

    title: Optional[str] = None
    organization_name: Optional[str] = None
    organization_id: Optional[int] = None
    location: Optional[str] = None
    remote_policy: Optional[str] = None
    job_description: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    source_platform: Optional[str] = None
    source_url: Optional[str] = None
    # When the post was listed publicly, if the page shows it.
    date_posted: Optional[date] = None

    # JD-extracted requirement fields.
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None
    experience_level: Optional[str] = None
    employment_type: Optional[str] = None
    education_required: Optional[str] = None
    visa_sponsorship_offered: Optional[bool] = None
    relocation_offered: Optional[bool] = None
    required_skills: Optional[list[str]] = None
    nice_to_have_skills: Optional[list[str]] = None

    # Enriched organization context (comes from the company's own site or a
    # web search — not the job-posting page alone).
    organization_website: Optional[str] = None
    organization_industry: Optional[str] = None
    organization_size: Optional[str] = None
    organization_headquarters: Optional[str] = None
    organization_description: Optional[str] = None
    tech_stack_hints: Optional[list[str]] = None

    # A short human-readable summary of what Claude was able to find, shown to
    # the user so they understand what the Companion looked up.
    research_notes: Optional[str] = None

    warning: Optional[str] = None
