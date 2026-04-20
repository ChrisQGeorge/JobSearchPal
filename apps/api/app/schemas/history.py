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
