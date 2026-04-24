"""Pydantic request/response models for history entities."""

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkExperienceIn(BaseModel):
    organization_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    remote_policy: Optional[str] = None
    summary: Optional[str] = None
    highlights: Optional[list[str]] = None
    technologies_used: Optional[list[str]] = None
    team_size: Optional[int] = None
    manager_name: Optional[str] = None
    reason_for_leaving: Optional[str] = None


class WorkExperienceOut(WorkExperienceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_name: Optional[str] = None


class EducationIn(BaseModel):
    organization_id: Optional[int] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    concentration: Optional[str] = None
    minor: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    gpa: Optional[float] = None
    honors: Optional[list[str]] = None
    thesis_title: Optional[str] = None
    thesis_summary: Optional[str] = None
    notes: Optional[str] = None


class EducationOut(EducationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_name: Optional[str] = None


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str | None = None
    proficiency: str | None = None
    years_experience: float | None = None
    last_used_date: date | None = None
    evidence_notes: str | None = None
    aliases: list[str] | None = None


class SkillOut(SkillIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # Populated by the list endpoint — number of entities this skill is linked
    # to across work_experience_skills + course_skills + entity_links. Zero
    # means the skill is orphaned.
    attachment_count: int = 0
    # Sum of WorkExperience durations for every job this skill is attached
    # to, rounded UP to the nearest whole year. Ongoing roles (no end_date)
    # run to today. Overlapping jobs count once per job (additive — two
    # concurrent roles each using Python contribute their full lengths).
    # None means no Work attachments or nothing with dates to measure.
    work_history_years: Optional[int] = None


class AchievementIn(BaseModel):
    # Preferred: an Organization row via FK, same combobox as Work/Education.
    # `issuer` is the legacy free-text field; API keeps both in sync (the
    # router mirrors the resolved org name into `issuer` on save so old
    # reads still work).
    organization_id: Optional[int] = None
    title: str
    type: Optional[str] = None
    date_awarded: Optional[date] = None
    issuer: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    supporting_document_url: Optional[str] = None


class AchievementOut(AchievementIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TimelineEvent(BaseModel):
    kind: str  # work / education / course / certification / project / publication / presentation / achievement / volunteer / custom
    id: int
    title: str
    subtitle: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    metadata: dict[str, Any] | None = None


# ---------- R1 remaining entities --------------------------------------------


class CourseIn(BaseModel):
    education_id: int
    code: Optional[str] = None
    name: str = Field(min_length=1, max_length=255)
    term: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    credits: Optional[float] = None
    grade: Optional[str] = None
    description: Optional[str] = None
    topics_covered: Optional[list[str]] = None
    notable_work: Optional[str] = None
    instructor: Optional[str] = None


class CourseOut(CourseIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CertificationIn(BaseModel):
    # Preferred issuer via Organization FK. `issuer` free text remains as
    # legacy / one-off fallback; router keeps them in sync.
    organization_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=255)
    issuer: Optional[str] = None
    issued_date: Optional[date] = None
    expires_date: Optional[date] = None
    credential_id: Optional[str] = None
    credential_url: Optional[str] = None
    verification_status: Optional[str] = None


class CertificationOut(CertificationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class LanguageIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    proficiency: Optional[str] = None
    certifications: Optional[list[Any]] = None


class LanguageOut(LanguageIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    summary: Optional[str] = None
    description_md: Optional[str] = None
    url: Optional[str] = None
    repo_url: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_ongoing: bool = False
    role: Optional[str] = None
    collaborators: Optional[list[Any]] = None
    highlights: Optional[list[str]] = None
    technologies_used: Optional[list[str]] = None
    visibility: str = "private"


class ProjectOut(ProjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PublicationIn(BaseModel):
    # Preferred venue via Organization FK. `venue` free text kept for
    # legacy / one-off rows; router keeps them in sync.
    organization_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=512)
    type: Optional[str] = None
    venue: Optional[str] = None
    publication_date: Optional[date] = None
    authors: Optional[list[str]] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    citation_count: Optional[int] = None
    notes: Optional[str] = None


class PublicationOut(PublicationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PresentationIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    venue: Optional[str] = None
    event_name: Optional[str] = None
    date_presented: Optional[date] = None
    audience_size: Optional[int] = None
    format: Optional[str] = None
    slides_url: Optional[str] = None
    recording_url: Optional[str] = None
    summary: Optional[str] = None


class PresentationOut(PresentationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class VolunteerWorkIn(BaseModel):
    # Preferred: an Organization row via FK (same combobox as Work/Education).
    # Either `organization_id` OR `organization` (free text) must be set —
    # enforced at the router level so the FK picker alone is sufficient. When
    # only the FK is set, the server mirrors the resolved org name into the
    # `organization` column so the DB's NOT NULL column stays populated.
    organization_id: Optional[int] = None
    organization: Optional[str] = Field(default=None, max_length=255)
    role: Optional[str] = None
    cause_area: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    hours_total: Optional[int] = None
    summary: Optional[str] = None
    highlights: Optional[list[str]] = None


class VolunteerWorkOut(VolunteerWorkIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ContactIn(BaseModel):
    organization_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=255)
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    other_links: Optional[list[Any]] = None
    notes: Optional[str] = None
    relationship_type: Optional[str] = None
    can_use_as_reference: Optional[str] = None  # yes / no / unknown
    last_contacted_date: Optional[date] = None


class ContactOut(ContactIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_name: Optional[str] = None


class CustomEventIn(BaseModel):
    type_label: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    event_metadata: Optional[dict[str, Any]] = None


class CustomEventOut(CustomEventIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Skill-link shapes -------------------------------------------------

class LinkedSkill(BaseModel):
    """A skill linked to a parent entity (Work or Course). Includes usage note."""

    model_config = ConfigDict(from_attributes=True)
    skill_id: int
    name: str
    category: Optional[str] = None
    proficiency: Optional[str] = None
    usage_notes: Optional[str] = None


class LinkSkillIn(BaseModel):
    skill_id: int
    usage_notes: Optional[str] = None


# ---------- Generic EntityLink -----------------------------------------------

class EntityLinkIn(BaseModel):
    from_entity_type: str
    from_entity_id: int
    to_entity_type: str
    to_entity_id: int
    relation: str = "related"
    note: Optional[str] = None


class EntityLinkOut(EntityLinkIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # Denormalized label for the "to" side, resolved server-side so the UI
    # doesn't have to fetch every linked entity individually.
    to_label: Optional[str] = None
