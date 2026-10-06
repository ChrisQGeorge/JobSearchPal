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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
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


class ApplyQuestionIn(BaseModel):
    """The "worth applying" yes/no question behind GO / MAYBE / NO-GO."""

    instructions: str = Field(min_length=1, max_length=4000)
    criteria_true: str = Field(min_length=1, max_length=1000)
    criteria_false: str = Field(min_length=1, max_length=1000)
    go_threshold: float = Field(ge=0, le=1)
    nogo_threshold: float = Field(ge=0, le=1)


class JevSettingsIn(BaseModel):
    """Full replacement write: a dimension missing from `overrides` (or
    mapped to null) resets to its default prompt; a weight missing from
    `weights` resets to 1.0. `apply` omitted keeps the saved apply
    question; send the defaults to reset it."""

    overrides: dict[str, Optional[DimensionOverrideIn]] = {}
    weights: dict[str, float] = {}
    apply: Optional[ApplyQuestionIn] = None


async def _decorate(cfg: dict, db: AsyncSession, user: User) -> dict:
    from app.api.v1.jobs import unacceptable_industries

    cfg["limits"] = {
        "min_criteria": MIN_CRITERIA,
        "max_criteria": MAX_CRITERIA,
        "max_weight": MAX_WEIGHT,
    }
    # What Jev's apply question is told to treat as a hard blocker
    # (managed on Settings → Criteria List, category "Industry").
    cfg["unacceptable_industries"] = await unacceptable_industries(db, user.id)
    return cfg


@router.get("/scoring-settings")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await _decorate(get_scoring_config(), db, user)


@router.put("/scoring-settings")
async def put_settings(
    payload: JevSettingsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if payload.apply is not None and payload.apply.nogo_threshold >= payload.apply.go_threshold:
        raise HTTPException(
            status_code=422,
            detail="The NO-GO threshold must be below the GO threshold.",
        )
    overrides = {
        k: (v.model_dump() if v is not None else None)
        for k, v in payload.overrides.items()
    }
    cfg = save_scoring_config(
        overrides,
        payload.weights,
        payload.apply.model_dump() if payload.apply is not None else None,
    )
    return await _decorate(cfg, db, user)
