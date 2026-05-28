"""MetricSnapshot materialization + job-strategy-advisor."""
from __future__ import annotations

import json
import logging
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
    # Select only the columns the aggregates need — NOT full ORM rows.
    # The full row drags job_description (Text) + jd_analysis +
    # fit_summary (JSON) along, which at a few thousand jobs is megabytes
    # of payload to count statuses. These four columns are all we touch.
    rows = (
        await db.execute(
            select(
                TrackedJob.status,
                TrackedJob.date_applied,
                TrackedJob.updated_at,
            ).where(
                TrackedJob.user_id == user_id,
                TrackedJob.deleted_at.is_(None),
            )
        )
    ).all()
    status_counts: dict[str, int] = {}
    applied_count = 0
    responded_count = 0
    offers_count = 0
    wins_count = 0
    ttr_days: list[float] = []
    applied_this_week = 0
    applied_30d = 0
    week_ago_pre = today - timedelta(days=7)
    thirty_ago_pre = today - timedelta(days=30)
    for status_v, date_applied_v, updated_at_v in rows:
        status_counts[status_v] = status_counts.get(status_v, 0) + 1
        if status_v in ("offer", "won"):
            offers_count += 1
        if status_v == "won":
            wins_count += 1
        if date_applied_v:
            applied_count += 1
            if status_v in POST_APPLY:
                responded_count += 1
                if updated_at_v:
                    d = (updated_at_v.date() - date_applied_v).days
                    if d >= 0:
                        ttr_days.append(d)
            if date_applied_v >= week_ago_pre:
                applied_this_week += 1
            if date_applied_v >= thirty_ago_pre:
                applied_30d += 1
    total_jobs = len(rows)
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

    return {
        "total_jobs": total_jobs,
        "status_counts": status_counts,
        "applied_count": applied_count,
        "responded_count": responded_count,
        "response_rate": round(responded_count / applied_count * 100, 1)
        if applied_count
        else None,
        "offers_count": offers_count,
        "wins_count": wins_count,
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
    # Only need status + source_platform — not the full rows (which drag
    # job_description / jd_analysis / fit_summary along). Bucket statuses
    # per source as a list of plain status strings.
    rows = (
        await db.execute(
            select(TrackedJob.status, TrackedJob.source_platform).where(
                TrackedJob.user_id == user.id,
                TrackedJob.deleted_at.is_(None),
            )
        )
    ).all()

    # Bucket by source_platform. Empty / None collapses to "(unknown)" so
    # the user can see how much of their pipeline is unattributed.
    by_source: dict[str, list[str]] = {}
    for status_v, source_platform_v in rows:
        key = (source_platform_v or "").strip() or "(unknown)"
        by_source.setdefault(key, []).append(status_v)

    out: list[FunnelBySourceRowOut] = []
    for source, statuses in by_source.items():
        applied_count = sum(
            1 for s in statuses if s in _FUNNEL_STAGES[0][1]
        )
        stages: list[FunnelStageOut] = []
        for stage, accepted in _FUNNEL_STAGES:
            n = sum(1 for s in statuses if s in accepted)
            rate = (
                round(100 * n / applied_count, 1) if applied_count else None
            )
            stages.append(
                FunnelStageOut(stage=stage, count=n, rate_from_applied=rate)
            )
        out.append(
            FunnelBySourceRowOut(
                source=source,
                total=len(statuses),
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


def _extract_json(text: str) -> Optional[dict]:
    """Re-export the canonical robust extractor — same one the JD
    analyzer uses. Repairs `\\'` and smart quotes, walks every `{`
    position with raw_decode, dict-only return type."""
    from app.api.v1.jobs import _extract_json_object
    return _extract_json_object(text)


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
            action="strategy",
        )
    except ClaudeCodeError as exc:
        log.warning("strategy failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")
    except Exception as exc:  # pragma: no cover
        log.exception("strategy unhandled error")
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected error talking to Claude: {type(exc).__name__}: {exc}",
        )

    data = _extract_json(final_text)
    if not isinstance(data, dict):
        # Surface what Claude actually returned so this stops being a
        # mystery 502. Mirrors the score-task error format.
        snippet = (final_text or "").strip()
        if len(snippet) > 600:
            snippet = snippet[:300] + " […] " + snippet[-300:]
        log.warning("strategy parse failure. Raw: %r", snippet)
        raise HTTPException(
            status_code=502,
            detail=(
                "Strategy skill returned no parseable JSON object. "
                f"Raw Claude output (truncated): {snippet!r}"
            ),
        )

    # Defensive coercion: Claude sometimes returns strings where lists
    # are expected, or vice versa. Normalize to the schema or skip.
    def _as_str_list(v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    headline = str(data.get("headline") or "").strip()
    if not headline:
        raise HTTPException(
            status_code=502,
            detail="Strategy skill returned a JSON object with no headline.",
        )
    return StrategyOut(
        headline=headline,
        working_well=_as_str_list(data.get("working_well"))[:6],
        struggling=_as_str_list(data.get("struggling"))[:6],
        next_actions=_as_str_list(data.get("next_actions"))[:8],
        risks=_as_str_list(data.get("risks"))[:4],
        warning=(str(data["warning"]) if data.get("warning") else None),
    )
