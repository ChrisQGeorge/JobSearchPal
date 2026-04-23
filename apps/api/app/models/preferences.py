"""Job preferences, work authorization, and demographics."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class JobPreferences(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "job_preferences"
    __table_args__ = (UniqueConstraint("user_id", name="uq_job_preferences_user"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    salary_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    salary_preferred_target: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    salary_acceptable_min: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    salary_unacceptable_below: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    total_comp_preferred_target: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    total_comp_acceptable_min: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)

    experience_level_preferred: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    experience_levels_acceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    experience_levels_unacceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    remote_policy_preferred: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    remote_policies_acceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    remote_policies_unacceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    max_commute_minutes_preferred: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_commute_minutes_acceptable: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    willing_to_relocate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    relocation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Preferred target locations, each with a radius in miles. Stored as a
    # JSON list of `{name: str, max_distance_miles: int|null}` so the UI
    # can offer a searchable city combobox + per-row slider without needing
    # a separate table. Order is user-meaningful (most-preferred first).
    preferred_locations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    travel_percent_preferred: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    travel_percent_acceptable_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    travel_percent_unacceptable_above: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    hours_per_week_preferred: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hours_per_week_acceptable_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    overtime_acceptable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    schedule_preferred: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    schedules_acceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    schedules_unacceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    employment_types_preferred: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    employment_types_acceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    employment_types_unacceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    equity_preference: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    benefits_required: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    benefits_preferred: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    earliest_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    latest_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notice_period_weeks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    dealbreakers_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dream_job_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class JobCriterion(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "job_criteria"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "value", name="uq_job_criterion"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(String(16), nullable=False)  # preferred / acceptable / unacceptable
    weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class WorkAuthorization(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "work_authorizations"
    __table_args__ = (UniqueConstraint("user_id", name="uq_work_authorization_user"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_country: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    current_location_city: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    current_location_region: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    citizenship_countries: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    work_authorization_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    visa_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    visa_issued_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    visa_expires_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    visa_sponsorship_required_now: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visa_sponsorship_required_future: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    relocation_countries_acceptable: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    security_clearance_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    security_clearance_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    security_clearance_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    export_control_considerations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Demographics(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "demographics"
    __table_args__ = (UniqueConstraint("user_id", name="uq_demographics_user"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    preferred_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    legal_first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    legal_middle_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    legal_last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    legal_suffix: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    pronouns: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pronouns_self_describe: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    gender_identity: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    gender_self_describe: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sex_assigned_at_birth: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    transgender_identification: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sexual_orientation: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sexual_orientation_self_describe: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    race_ethnicity: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ethnicity_self_describe: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    veteran_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    disability_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    disability_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    accommodation_needs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    age_bracket: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    first_generation_college_student: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class ResumeProfile(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """Contact/header info the user wants on generated resumes, cover letters,
    and other tailored documents. Kept separate from the login User row
    (which holds display_name + email) and from Demographics (voluntary
    self-id) so that document personas can be edited independently.
    """

    __tablename__ = "resume_profile"
    __table_args__ = (UniqueConstraint("user_id", name="uq_resume_profile_user"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    headline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    github_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Free-form list of { "label": str, "url": str } for anything else
    # (Stack Overflow, Medium, personal blog, speaker reel, etc.).
    other_links: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # Optional reusable summary paragraph. Tailor prompts will rephrase per
    # job, but this gives them a seed to work from if the user prefers.
    professional_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DemographicSharePolicy(Base, IdMixin, TimestampMixin):
    __tablename__ = "demographic_share_policies"
    __table_args__ = (
        UniqueConstraint("user_id", "field_name", name="uq_demographic_share_policy"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    policy: Mapped[str] = mapped_column(String(32), nullable=False, default="ask_each_time")
    override_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
