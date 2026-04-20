"""Pydantic models for the Organization endpoints."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


ORG_TYPES = {
    "company",
    "university",
    "nonprofit",
    "government",
    "conference",
    "publisher",
    "agency",
    "other",
}


class OrganizationIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(default="company", max_length=32)
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    headquarters_location: Optional[str] = None
    founded_year: Optional[int] = None
    description: Optional[str] = None
    research_notes: Optional[str] = None


class OrganizationOut(OrganizationIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class OrganizationSummary(BaseModel):
    """Lightweight shape used in the combobox typeahead and elsewhere."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: str
