"""Canonical history entities: work, education, skills, projects, publications, etc."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class WorkExperience(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "work_experiences"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlights: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    technologies_used: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    team_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manager_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reason_for_leaving: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class WorkExperienceSkill(Base, IdMixin, TimestampMixin):
    __tablename__ = "work_experience_skills"
    __table_args__ = (
        UniqueConstraint("work_experience_id", "skill_id", name="uq_work_experience_skill"),
    )

    work_experience_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("work_experiences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usage_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Education(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "educations"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The school / university, stored as an Organization row. Nullable so we can
    # soft-delete the institution row without orphaning the education record.
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    degree: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    field_of_study: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    minor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gpa: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)
    honors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    thesis_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    thesis_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CourseSkill(Base, IdMixin, TimestampMixin):
    """Many-to-many: a course teaches / exercised certain skills."""

    __tablename__ = "course_skills"
    __table_args__ = (
        UniqueConstraint("course_id", "skill_id", name="uq_course_skill"),
    )

    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usage_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Course(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "courses"

    education_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("educations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    term: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    credits: Mapped[Optional[float]] = mapped_column(Numeric(4, 1), nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    topics_covered: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notable_work: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instructor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Certification(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "certifications"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    issued_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expires_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    credential_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    credential_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    verification_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)


class Skill(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "skills"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    proficiency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    years_experience: Mapped[Optional[float]] = mapped_column(Numeric(4, 1), nullable=True)
    last_used_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    evidence_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Language(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "languages"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    proficiency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    certifications: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


class Project(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    repo_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_ongoing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    role: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    collaborators: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    highlights: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    technologies_used: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")


class Publication(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "publications"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    publication_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    authors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    citation_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Presentation(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "presentations"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    venue: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    event_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_presented: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    audience_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    slides_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    recording_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Achievement(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "achievements"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    date_awarded: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    issuer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    supporting_document_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)


class VolunteerWork(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "volunteer_works"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cause_area: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    hours_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlights: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


class Contact(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "contacts"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    other_links: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relationship_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_contacted_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class CustomEvent(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "custom_events"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type_label: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # NOTE: stored as `event_metadata` (not `metadata`) to avoid colliding with
    # SQLAlchemy's DeclarativeBase.metadata reserved name.
    event_metadata: Mapped[Optional[dict]] = mapped_column(
        "event_metadata", JSON, nullable=True
    )
