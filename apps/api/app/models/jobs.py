"""Companies, tracked jobs, application events, interview rounds and artifacts."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class Organization(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """A generic organization — employer, school, cert issuer, conference, etc.

    Referenced by WorkExperience, Education, TrackedJob, Contact, and anywhere
    else the user needs to link a dated history entry to a real-world entity.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Narrow type hint — drives icons / filters in the UI. Free-form to allow
    # future additions without a migration.
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="company", index=True,
    )  # company / university / nonprofit / government / conference / publisher / agency / other
    website: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    headquarters_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    founded_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    research_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_links: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    reputation_signals: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tech_stack_hints: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


class TrackedJob(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tracked_jobs"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    job_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    source_platform: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_policy: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    salary_min: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    equity_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="watching", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jd_analysis: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fit_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Explicit JD-extracted fields (populated by fetch-from-url or manually).
    experience_years_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    experience_years_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    experience_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    education_required: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    visa_sponsorship_offered: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    relocation_offered: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Skills the JD calls out as required vs nice-to-have. Stored as JSON
    # arrays of strings; the UI matches them against the user's Skill catalog
    # at render time and offers +Add buttons for misses.
    required_skills: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    nice_to_have_skills: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    date_posted: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_discovered: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_applied: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_closed: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class ApplicationEvent(Base, IdMixin, TimestampMixin):
    __tablename__ = "application_events"

    tracked_job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    related_round_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("interview_rounds.id", ondelete="SET NULL"), nullable=True
    )
    attachments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


class InterviewRound(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "interview_rounds"

    tracked_job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    round_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    location_or_link: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    interviewers: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    self_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prep_notes_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class JobFetchQueue(Base, IdMixin, TimestampMixin):
    """Queue of URLs to fetch + auto-create as TrackedJob records.

    A background worker polls rows with state='queued', runs the URL-fetch
    flow, and on success creates a TrackedJob seeded with the fetched fields
    plus any user-supplied overrides (status, date_applied, date_closed).
    """

    __tablename__ = "job_fetch_queue"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)

    # Preset overrides applied to the created TrackedJob.
    desired_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    desired_priority: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    desired_date_applied: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    desired_date_closed: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    desired_date_posted: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    desired_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Processing state machine: queued → processing → done | error
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # When set, the worker won't claim this row until the given time. Used
    # for rate-limit / usage-quota cooldowns so a queue full of URLs backs
    # off and resumes automatically once tokens refresh.
    resume_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True
    )
    # --- Generic task-queue fields (migration 0012). ------------------------
    # The `url`/`desired_*` columns above are fetch-specific; these four make
    # the same table capable of carrying any Companion task. `kind`
    # discriminates — "fetch" (existing), "score", "tailor", "humanize",
    # "strategy", "interview_prep", "interview_retro", "org_research",
    # "autofill", "resume_ingest". The worker dispatches on this column.
    # `payload` carries per-kind args (e.g. {"tracked_job_id": 42} for score);
    # `result` is filled in on success (e.g. {"generated_document_id": 101}).
    kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class InterviewArtifact(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "interview_artifacts"

    interview_round_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("interview_rounds.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tracked_job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
