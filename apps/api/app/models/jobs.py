"""Companies, tracked jobs, application events, interview rounds and artifacts."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
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


class Company(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
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
    company_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
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
