"""Auto-apply settings API (R11).

GET  /api/v1/auto-apply/settings  — read
PUT  /api/v1/auto-apply/settings  — upsert
POST /api/v1/auto-apply/run-now   — force one immediate poller tick
GET  /api/v1/auto-apply/preview   — list candidate jobs for the next tick
GET  /api/v1/auto-apply/today     — usage stats for today's UTC day

Settings live one-row-per-user in `auto_apply_settings`. The poller in
`app/skills/auto_apply.py` reads these on every tick.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.models.applications import AutoApplySettings
from app.models.user import User
from app.skills import auto_apply as auto_apply_worker

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auto-apply", tags=["auto-apply"])


class AutoApplySettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    daily_cap: int
    min_fit_score: Optional[int] = None
    only_known_ats: bool
    pause_start_hour: Optional[int] = None
    pause_end_hour: Optional[int] = None
    last_run_at: Optional[datetime] = None
    last_browser_visible_at: Optional[datetime] = None


class AutoApplySettingsIn(BaseModel):
    enabled: bool = False
    daily_cap: int = Field(default=5, ge=0, le=100)
    min_fit_score: Optional[int] = Field(default=None, ge=0, le=100)
    only_known_ats: bool = False
    pause_start_hour: Optional[int] = Field(default=None, ge=0, le=23)
    pause_end_hour: Optional[int] = Field(default=None, ge=0, le=23)


async def _get_or_create(db: AsyncSession, user_id: int) -> AutoApplySettings:
    row = (
        await db.execute(
            select(AutoApplySettings).where(AutoApplySettings.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = AutoApplySettings(user_id=user_id)
    db.add(row)
    await db.flush()
    return row


@router.get("/settings", response_model=AutoApplySettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AutoApplySettings:
    row = await _get_or_create(db, user.id)
    await db.commit()
    return row


@router.put("/settings", response_model=AutoApplySettingsOut)
async def update_settings(
    payload: AutoApplySettingsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AutoApplySettings:
    row = await _get_or_create(db, user.id)
    row.enabled = payload.enabled
    row.daily_cap = payload.daily_cap
    row.min_fit_score = payload.min_fit_score
    row.only_known_ats = payload.only_known_ats
    row.pause_start_hour = payload.pause_start_hour
    row.pause_end_hour = payload.pause_end_hour
    await db.commit()
    await db.refresh(row)
    return row


class HeartbeatOut(BaseModel):
    last_browser_visible_at: Optional[datetime]
    grace_seconds: int


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HeartbeatOut:
    """Bumped by the /browser page while the tab is visible. The
    poller's _is_browser_visible_recent check uses this value as the
    gate that prevents auto-apply from running when the user can't
    see what the agent is doing."""
    row = await _get_or_create(db, user.id)
    row.last_browser_visible_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return HeartbeatOut(
        last_browser_visible_at=row.last_browser_visible_at,
        grace_seconds=auto_apply_worker.HEARTBEAT_GRACE_SECONDS,
    )


class RunNowOut(BaseModel):
    spawned: int
    last_run_at: Optional[datetime]


@router.post("/run-now", response_model=RunNowOut)
async def run_now(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RunNowOut:
    """Force one tick for the current user without waiting for the
    poller. Useful for "I just turned this on, do something." Subject
    to the same daily-cap / min-score / pause-window gates as the
    background poller."""
    row = await _get_or_create(db, user.id)
    if not row.enabled:
        raise HTTPException(
            status_code=409,
            detail="Auto-apply is disabled — turn it on first.",
        )
    # Mirror the poller's visibility gate so the run-now button can't
    # bypass the "browser must be visible" rule.
    now = auto_apply_worker._now()
    if not auto_apply_worker._is_browser_visible_recent(
        now, row.last_browser_visible_at
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The /browser page must be open and visible for auto-apply "
                "to fire. Open it and try again."
            ),
        )
    spawned = await auto_apply_worker._tick_user(db, user.id, row)
    await db.commit()
    return RunNowOut(spawned=spawned, last_run_at=row.last_run_at)


class PreviewJobOut(BaseModel):
    tracked_job_id: int
    title: str
    organization: Optional[str] = None
    fit_score: Optional[int] = None
    source_url: Optional[str] = None
    ats: Optional[str] = None


class PreviewOut(BaseModel):
    settings: AutoApplySettingsOut
    used_today: int
    remaining_today: int
    candidates: list[PreviewJobOut]


@router.get("/preview", response_model=PreviewOut)
async def preview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PreviewOut:
    """Show what the next tick would do without enqueueing anything."""
    from app.models.jobs import Organization
    from app.skills.apply_run import _detect_ats

    row = await _get_or_create(db, user.id)
    await db.commit()

    now = auto_apply_worker._now()
    used = await auto_apply_worker._count_today_runs(
        db, user.id, auto_apply_worker._utc_midnight(now)
    )
    remaining = max(0, int(row.daily_cap or 0) - used)

    candidates = await auto_apply_worker._candidate_jobs(
        db,
        user.id,
        min_fit_score=row.min_fit_score,
        only_known_ats=bool(row.only_known_ats),
        limit=max(remaining, 5),
    )

    org_ids = [c.organization_id for c in candidates if c.organization_id]
    org_name_map: dict[int, str] = {}
    if org_ids:
        rows = (
            await db.execute(
                select(Organization.id, Organization.name).where(
                    Organization.id.in_(org_ids)
                )
            )
        ).all()
        org_name_map = {r[0]: r[1] for r in rows}

    out_jobs: list[PreviewJobOut] = []
    for j in candidates:
        score: Optional[int] = None
        if isinstance(j.fit_summary, dict):
            raw = j.fit_summary.get("score")
            if isinstance(raw, (int, float)):
                score = int(raw)
        ats = await _detect_ats(j.source_url or "")
        out_jobs.append(
            PreviewJobOut(
                tracked_job_id=j.id,
                title=j.title,
                organization=org_name_map.get(j.organization_id) if j.organization_id else None,
                fit_score=score,
                source_url=j.source_url,
                ats=ats,
            )
        )

    return PreviewOut(
        settings=AutoApplySettingsOut.model_validate(row),
        used_today=used,
        remaining_today=remaining,
        candidates=out_jobs,
    )


class TodayOut(BaseModel):
    used_today: int
    daily_cap: int
    remaining_today: int


@router.get("/today", response_model=TodayOut)
async def today_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TodayOut:
    row = await _get_or_create(db, user.id)
    await db.commit()
    now = auto_apply_worker._now()
    used = await auto_apply_worker._count_today_runs(
        db, user.id, auto_apply_worker._utc_midnight(now)
    )
    return TodayOut(
        used_today=used,
        daily_cap=int(row.daily_cap or 0),
        remaining_today=max(0, int(row.daily_cap or 0) - used),
    )
