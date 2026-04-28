"""MetricSnapshot materialization + job-strategy-advisor."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.jobs import InterviewRound, TrackedJob
from app.models.operational import MetricSnapshot
from app.models.user import User
from app.skills.runner import ClaudeCodeError, run_claude_prompt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/metrics", tags=["metrics"])


POST_APPLY = {"responded", "screening", "interviewing", "assessment", "offer", "won"}


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    metric_key: str
    period: str
    period_start: Optional[date]
    period_end: Optional[date]
    value: Optional[dict]
    computed_at: datetime
    created_at: datetime


async def _compute_snapshot(db: AsyncSession, user_id: int) -> dict[str, Any]:
    today = date.today()
    jobs = list(
        (
            await db.execute(
                select(TrackedJob).where(
                    TrackedJob.user_id == user_id,
                    TrackedJob.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    status_counts: dict[str, int] = {}
    for j in jobs:
        status_counts[j.status] = status_counts.get(j.status, 0) + 1
    applied = [j for j in jobs if j.date_applied]
    responded = [j for j in applied if j.status in POST_APPLY]
    offers = [j for j in jobs if j.status in ("offer", "won")]
    wins = [j for j in jobs if j.status == "won"]

    # Days-to-first-response: updated_at of jobs that moved to POST_APPLY minus date_applied.
    ttr_days: list[float] = []
    for j in applied:
        if j.status in POST_APPLY and j.updated_at and j.date_applied:
            d = (j.updated_at.date() - j.date_applied).days
            if d >= 0:
                ttr_days.append(d)
    rounds = list(
        (
            await db.execute(
                select(InterviewRound)
                .join(TrackedJob, TrackedJob.id == InterviewRound.tracked_job_id)
                .where(
                    TrackedJob.user_id == user_id,
                    InterviewRound.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    )
    rounds_passed = sum(1 for r in rounds if r.outcome == "passed")
    rounds_failed = sum(1 for r in rounds if r.outcome == "failed")

    week_ago = today - timedelta(days=7)
    thirty_ago = today - timedelta(days=30)
    applied_this_week = sum(1 for j in applied if j.date_applied >= week_ago)
    applied_30d = sum(1 for j in applied if j.date_applied >= thirty_ago)

    return {
        "total_jobs": len(jobs),
        "status_counts": status_counts,
        "applied_count": len(applied),
        "responded_count": len(responded),
        "response_rate": round(len(responded) / len(applied) * 100, 1)
        if applied
        else None,
        "offers_count": len(offers),
        "wins_count": len(wins),
        "applied_this_week": applied_this_week,
        "applied_last_30_days": applied_30d,
        "avg_days_to_response": round(sum(ttr_days) / len(ttr_days), 1)
        if ttr_days
        else None,
        "rounds_total": len(rounds),
        "rounds_passed": rounds_passed,
        "rounds_failed": rounds_failed,
        "round_pass_rate": round(rounds_passed / (rounds_passed + rounds_failed) * 100, 1)
        if (rounds_passed + rounds_failed)
        else None,
    }


@router.post("/snapshot", response_model=SnapshotOut)
async def create_snapshot(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MetricSnapshot:
    value = await _compute_snapshot(db, user.id)
    snap = MetricSnapshot(
        user_id=user.id,
        metric_key="pipeline_summary",
        period="ad_hoc",
        period_start=None,
        period_end=date.today(),
        value=value,
        computed_at=datetime.now(tz=timezone.utc),
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap


class FunnelStageOut(BaseModel):
    stage: str
    count: int
    rate_from_applied: Optional[float] = None  # % of `applied` that reached this stage


class FunnelBySourceRowOut(BaseModel):
    source: str  # source_platform name, or "(unknown)" for null
    total: int
    stages: list[FunnelStageOut]


# The funnel stages, in order, plus the set of TrackedJob statuses that
# count as "having reached" that stage. A row "reaches" a later stage if
# its current status OR any historical event has been at that stage; we
# approximate via current-status-or-later because we don't track full
# status history (yet).
_FUNNEL_STAGES: list[tuple[str, set[str]]] = [
    ("applied", {"applied", "phone_screen", "take_home", "onsite", "final_round", "offer", "hired"}),
    ("phone_screen", {"phone_screen", "take_home", "onsite", "final_round", "offer", "hired"}),
    ("onsite", {"onsite", "final_round", "offer", "hired"}),
    ("offer", {"offer", "hired"}),
    ("hired", {"hired"}),
]


@router.get("/funnel-by-source", response_model=list[FunnelBySourceRowOut])
async def funnel_by_source(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FunnelBySourceRowOut]:
    """Application-to-response funnel grouped by source_platform.

    Useful for "where am I getting traction?" — you might find that 80% of
    your interviews come from referrals while LinkedIn applies are mostly
    ghosted. Returned rows are sorted by total applications descending so
    the heaviest channels show first.

    The "reached stage X" rule treats current status as monotonic: a job
    at status=onsite has reached applied + phone_screen + onsite. The
    funnel doesn't count jobs that bypassed `applied` (e.g. recruiter
    inbound that skipped straight to interest)."""
    rows = (
        await db.execute(
            select(TrackedJob).where(
                TrackedJob.user_id == user.id,
                TrackedJob.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    # Bucket by source_platform. Empty / None collapses to "(unknown)" so
    # the user can see how much of their pipeline is unattributed.
    by_source: dict[str, list[TrackedJob]] = {}
    for j in rows:
        key = (j.source_platform or "").strip() or "(unknown)"
        by_source.setdefault(key, []).append(j)

    out: list[FunnelBySourceRowOut] = []
    for source, items in by_source.items():
        applied_count = sum(
            1 for j in items if j.status in _FUNNEL_STAGES[0][1]
        )
        stages: list[FunnelStageOut] = []
        for stage, accepted in _FUNNEL_STAGES:
            n = sum(1 for j in items if j.status in accepted)
            rate = (
                round(100 * n / applied_count, 1) if applied_count else None
            )
            stages.append(
                FunnelStageOut(stage=stage, count=n, rate_from_applied=rate)
            )
        out.append(
            FunnelBySourceRowOut(
                source=source,
                total=len(items),
                stages=stages,
            )
        )
    out.sort(key=lambda r: -r.total)
    return out


@router.get("/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MetricSnapshot]:
    stmt = (
        select(MetricSnapshot)
        .where(MetricSnapshot.user_id == user.id)
        .order_by(MetricSnapshot.computed_at.desc())
        .limit(50)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------- job-strategy-advisor -------------------------------------------


_STRATEGY_PROMPT = """You're advising a job-seeker on pipeline strategy.

Recent pipeline snapshot:
{snapshot}

Historical snapshots (if any) — look for trends:
{history}

Top unresolved tracked jobs (those not in won/lost/withdrawn/ghosted/archived):
{hot_jobs}

Return ONE JSON object, no prose, no markdown fences:

{{
  "headline": string,             // one-sentence read of where they stand
  "working_well": string[],       // 2-4 bullets on what the data says is working
  "struggling": string[],         // 2-4 bullets on what's weak or stalling
  "next_actions": string[],       // 3-6 concrete, specific next actions
  "risks": string[],              // 1-3 watch-outs (burnout pace, pipeline gaps, etc.)
  "warning": string | null
}}
"""


class StrategyOut(BaseModel):
    headline: str
    working_well: list[str] = []
    struggling: list[str] = []
    next_actions: list[str] = []
    risks: list[str] = []
    warning: Optional[str] = None


_JSON_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        inner = "\n".join(text.splitlines()[1:]).rsplit("```", 1)[0]
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


@router.post("/strategy", response_model=StrategyOut)
async def job_strategy(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StrategyOut:
    # Fresh snapshot for the live view.
    current = await _compute_snapshot(db, user.id)

    # Previous snapshots for trend-spotting.
    past = list(
        (
            await db.execute(
                select(MetricSnapshot)
                .where(MetricSnapshot.user_id == user.id)
                .order_by(MetricSnapshot.computed_at.desc())
                .limit(5)
            )
        ).scalars().all()
    )
    history = [
        {
            "computed_at": s.computed_at.isoformat(),
            "value": s.value,
        }
        for s in past
    ]

    hot_jobs = list(
        (
            await db.execute(
                select(TrackedJob)
                .where(
                    TrackedJob.user_id == user.id,
                    TrackedJob.deleted_at.is_(None),
                    TrackedJob.status.in_(
                        [
                            "watching",
                            "interested",
                            "applied",
                            "responded",
                            "screening",
                            "interviewing",
                            "assessment",
                            "offer",
                        ]
                    ),
                )
                .order_by(TrackedJob.updated_at.desc())
                .limit(15)
            )
        ).scalars().all()
    )
    hot = [
        {
            "id": j.id,
            "title": j.title,
            "status": j.status,
            "date_applied": j.date_applied.isoformat() if j.date_applied else None,
            "priority": j.priority,
            "fit_score": (j.fit_summary or {}).get("score")
            if isinstance(j.fit_summary, dict)
            else None,
        }
        for j in hot_jobs
    ]

    prompt = _STRATEGY_PROMPT.format(
        snapshot=json.dumps(current, indent=2),
        history=json.dumps(history, indent=2) if history else "(no history yet)",
        hot_jobs=json.dumps(hot, indent=2) if hot else "(no active jobs)",
    )

    from app.skills.queue_bus import run_claude_to_bus

    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source="strategy",
            item_id=f"strategy:{user.id}",
            label="Strategy briefing",
            allowed_tools=[],
            timeout_seconds=120,
        )
    except ClaudeCodeError as exc:
        log.warning("strategy failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json(final_text) or {}
    headline = (data.get("headline") or "").strip()
    if not headline:
        raise HTTPException(
            status_code=502, detail="Strategy skill returned no headline."
        )
    return StrategyOut(
        headline=headline,
        working_well=list(data.get("working_well") or [])[:6],
        struggling=list(data.get("struggling") or [])[:6],
        next_actions=list(data.get("next_actions") or [])[:8],
        risks=list(data.get("risks") or [])[:4],
        warning=data.get("warning"),
    )
