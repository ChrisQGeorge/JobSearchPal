"""Jev scoring-prompt settings API.

Exposes the five scoring dimensions' prompts (instructions + ordered
worst→best criteria) and their weights in the overall average, so the
user can tell Jev what to prioritize from Settings → Jev scoring. The
candidate profile/state block and the apply yes/no judgment are
deliberately not exposed. Overrides persist on the claude_config volume
(see app/skills/jev.py) and apply to the next score run — no restart.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.models.user import User
from app.skills.jev import (
    MAX_CRITERIA,
    MAX_WEIGHT,
    MIN_CRITERIA,
    get_scoring_config,
    save_scoring_config,
)

router = APIRouter(prefix="/jev", tags=["jev"])


class DimensionOverrideIn(BaseModel):
    instructions: str = Field(min_length=1, max_length=2000)
    criteria: list[str] = Field(
        min_length=MIN_CRITERIA, max_length=MAX_CRITERIA
    )


class JevSettingsIn(BaseModel):
    """Full replacement write: a dimension missing from `overrides` (or
    mapped to null) resets to its default prompt; a weight missing from
    `weights` resets to 1.0."""

    overrides: dict[str, Optional[DimensionOverrideIn]] = {}
    weights: dict[str, float] = {}


@router.get("/scoring-settings")
async def get_settings(user: User = Depends(get_current_user)) -> dict:
    cfg = get_scoring_config()
    cfg["limits"] = {
        "min_criteria": MIN_CRITERIA,
        "max_criteria": MAX_CRITERIA,
        "max_weight": MAX_WEIGHT,
    }
    return cfg


@router.put("/scoring-settings")
async def put_settings(
    payload: JevSettingsIn,
    user: User = Depends(get_current_user),
) -> dict:
    overrides = {
        k: (v.model_dump() if v is not None else None)
        for k, v in payload.overrides.items()
    }
    cfg = save_scoring_config(overrides, payload.weights)
    cfg["limits"] = {
        "min_criteria": MIN_CRITERIA,
        "max_criteria": MAX_CRITERIA,
        "max_weight": MAX_WEIGHT,
    }
    return cfg
