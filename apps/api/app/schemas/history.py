"""Pydantic request/response models for history entities."""

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkExperienceIn(BaseModel):
    company_id: int | None = None
    title: str = Field(min_length=1, max_length=255)
    start_date: date | None = None
    end_date: date | None = None
    location: str | None = None
    employment_type: str | None = None
    summary: str | None = None
    highlights: list[str] | None = None
    technologies_used: list[str] | None = None
    team_size: int | None = None
    manager_name: str | None = None
    reason_for_leaving: str | None = None


class WorkExperienceOut(WorkExperienceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class EducationIn(BaseModel):
    institution: str = Field(min_length=1, max_length=255)
    degree: str | None = None
    field_of_study: str | None = None
    minor: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    gpa: float | None = None
    honors: list[str] | None = None
    thesis_title: str | None = None
    thesis_summary: str | None = None
    notes: str | None = None


class EducationOut(EducationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    category: str | None = None
    proficiency: str | None = None
    years_experience: float | None = None
    last_used_date: date | None = None
    evidence_notes: str | None = None


class SkillOut(SkillIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AchievementIn(BaseModel):
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
