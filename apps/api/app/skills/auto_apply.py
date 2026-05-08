"""Auto-apply background poller (R11).

Wakes every TICK seconds. For every user with `AutoApplySettings.enabled=True`:

  1. Compute today's submission budget = max(0, daily_cap - applied_today).
     "applied_today" counts ApplicationRun rows in any non-failed state
     started since the user-local midnight.
  2. Pull `interested` TrackedJob rows that pass the user's policy gates
     (min_fit_score, only_known_ats) and don't already have an active
     ApplicationRun.
  3. Insert ApplicationRun(state=queued) + JobFetchQueue(kind=apply_run)
     rows for the top `budget` jobs, ordered by fit_summary.score desc
     (tie-break by date_discovered).
  4. Stamp `last_run_at` so the user can see when the auto-pilot last
     attempted scheduling.

Single user → one row enqueued at a time, no parallelism. The queue
worker still serializes by claim. Daily cap is the *hard* throttle —
all other gates (min_fit_score, only_known_ats, status filter) are
about *quality*, not throughput.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.applications import ApplicationRun, AutoApplySettings
from app.models.jobs import JobFetchQueue, TrackedJob
from app.models.user import User
from app.skills.apply_run import _detect_ats

log = logging.getLogger(__name__)

# Wake every 5 minutes. Auto-apply isn't latency-sensitive and the
# Claude Pro/API budget is the real bottleneck — the queue worker
# itself spaces submissions much further apart than we'd ever poll.
TICK_SECONDS = 5 * 60

# Hard ceiling on per-tick spawns regardless of daily_cap to prevent a
# misconfigured "daily_cap=999" from flooding the queue.
MAX_SPAWN_PER_TICK = 10

# How recent the /browser-page heartbeat must be (in seconds) for the
# auto-apply poller to consider the user "watching." If the user
# closes / hides the /browser tab, heartbeats stop and runs pause
# automatically within this window. The /browser page bumps the
# heartbeat every 10s while visible, so 60s is a comfortable margin
# for a missed tick.
HEARTBEAT_GRACE_SECONDS = 60


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _utc_midnight(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _is_in_pause_window(
    now: datetime, start: Optional[int], end: Optional[int]
) -> bool:
    """[start, end) hour-of-day. None on either side = always-on."""
    if start is None or end is None:
        return False
    h = now.hour
    if start == end:
        return False  # zero-length window = always-on
    if start < end:
        return start <= h < end
    # Wraps midnight (e.g. start=22, end=6 means 10pm–6am)
    return h >= start or h < end


async def _count_today_runs(db: AsyncSession, user_id: int, since: datetime) -> int:
    stmt = select(func.count(ApplicationRun.id)).where(
        ApplicationRun.user_id == user_id,
        ApplicationRun.created_at >= since,
        ApplicationRun.state.in_(
            ("queued", "running", "awaiting_user", "submitted")
        ),
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def _candidate_jobs(
    db: AsyncSession,
    user_id: int,
    *,
    min_fit_score: Optional[int],
    only_known_ats: bool,
    limit: int,
) -> list[TrackedJob]:
    """Pull the user's `interested` jobs that are eligible for an
    auto-apply run. Skips anything that already has a non-terminal
    ApplicationRun."""

    # Subquery: tracked_job_ids that already have an active or
    # successful ApplicationRun.
    active_run_subq = (
        select(ApplicationRun.tracked_job_id)
        .where(
            ApplicationRun.user_id == user_id,
            ApplicationRun.state.in_(
                ("queued", "running", "awaiting_user", "submitted")
            ),
        )
        .scalar_subquery()
    )

    stmt = (
        select(TrackedJob)
        .where(
            TrackedJob.user_id == user_id,
            TrackedJob.deleted_at.is_(None),
            TrackedJob.status == "interested",
            TrackedJob.source_url.isnot(None),
            TrackedJob.source_url != "",
            TrackedJob.id.notin_(active_run_subq),
        )
        # MySQL doesn't understand PG's `NULLS LAST` keyword. Emulate
        # it by sorting on the IS NULL boolean first (False sorts
        # before True → non-null rows come first), then the actual
        # date desc, then id desc as a tiebreaker.
        .order_by(
            TrackedJob.date_discovered.is_(None),
            TrackedJob.date_discovered.desc(),
            TrackedJob.id.desc(),
        )
        # Pull a wider window than `limit` because we still need to
        # filter by fit_score / ATS in Python (fit_summary is JSON).
        .limit(max(limit * 4, 25))
    )
    rows = list((await db.execute(stmt)).scalars().all())

    out: list[TrackedJob] = []
    for j in rows:
        if min_fit_score is not None:
            score = None
            if isinstance(j.fit_summary, dict):
                raw = j.fit_summary.get("score")
                if isinstance(raw, (int, float)):
                    score = int(raw)
            if score is None or score < min_fit_score:
                continue
        if only_known_ats:
            ats = await _detect_ats(j.source_url or "")
            if not ats:
                continue
        out.append(j)
        if len(out) >= limit:
            break

    # Sort by best fit-score desc so the top-N picks are highest quality.
    def _score_key(j: TrackedJob) -> int:
        if isinstance(j.fit_summary, dict):
            raw = j.fit_summary.get("score")
            if isinstance(raw, (int, float)):
                return int(raw)
        return 0

    out.sort(key=_score_key, reverse=True)
    return out[:limit]


async def _enqueue_apply_run(
    db: AsyncSession, user_id: int, job: TrackedJob
) -> Optional[int]:
    """Insert one ApplicationRun + matching JobFetchQueue row. Returns
    the new run id (or None on insert failure)."""
    run = ApplicationRun(
        user_id=user_id,
        tracked_job_id=job.id,
        tier="generic",
        state="queued",
    )
    db.add(run)
    await db.flush()

    queued = JobFetchQueue(
        user_id=user_id,
        kind="apply_run",
        label=f"Auto-apply → {job.title[:80]}"[:512],
        url=job.source_url or "",
        payload={
            "application_run_id": run.id,
            "tracked_job_id": job.id,
            "auto": True,
        },
        state="queued",
    )
    db.add(queued)
    await db.flush()
    run.queue_id = queued.id
    return run.id


def _is_browser_visible_recent(
    now: datetime, last_heartbeat: Optional[datetime]
) -> bool:
    """True if the user has had the /browser page open + visible
    within the heartbeat grace window. False otherwise — and the
    poller treats that as "do nothing this tick."""
    if last_heartbeat is None:
        return False
    return (now - last_heartbeat).total_seconds() <= HEARTBEAT_GRACE_SECONDS


async def _tick_user(
    db: AsyncSession, user_id: int, settings: AutoApplySettings
) -> int:
    """Process one user. Returns the number of runs spawned this tick."""
    if not settings.enabled:
        return 0

    now = _now()
    if _is_in_pause_window(now, settings.pause_start_hour, settings.pause_end_hour):
        return 0

    # Visibility gate — only fire when the user has the /browser page
    # actively visible. Stops the auto-apply loop the moment they close
    # the tab, switch tabs, or close their laptop.
    if not _is_browser_visible_recent(now, settings.last_browser_visible_at):
        return 0

    used = await _count_today_runs(db, user_id, _utc_midnight(now))
    remaining = max(0, int(settings.daily_cap or 0) - used)
    remaining = min(remaining, MAX_SPAWN_PER_TICK)
    if remaining <= 0:
        settings.last_run_at = now
        return 0

    candidates = await _candidate_jobs(
        db,
        user_id,
        min_fit_score=settings.min_fit_score,
        only_known_ats=bool(settings.only_known_ats),
        limit=remaining,
    )

    spawned = 0
    for job in candidates:
        rid = await _enqueue_apply_run(db, user_id, job)
        if rid is not None:
            spawned += 1
    settings.last_run_at = now
    if spawned:
        log.info(
            "auto-apply: spawned %d run(s) for user_id=%s (cap=%d, used_today=%d)",
            spawned, user_id, settings.daily_cap, used,
        )
    return spawned


async def _tick_all() -> None:
    async with SessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(AutoApplySettings).where(AutoApplySettings.enabled.is_(True))
                )
            ).scalars().all()
        )
        if not rows:
            return
        # Confirm each user is still active (not soft-deleted) before
        # spending compute on candidate selection.
        active_ids = set(
            (
                await db.execute(
                    select(User.id).where(
                        User.id.in_([r.user_id for r in rows]),
                        User.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
        )
        for s in rows:
            if s.user_id not in active_ids:
                continue
            try:
                await _tick_user(db, s.user_id, s)
                await db.commit()
            except Exception:
                log.exception("auto-apply tick failed for user_id=%s", s.user_id)
                await db.rollback()


async def run_forever() -> None:
    """Main loop. Wakes every TICK_SECONDS and ticks every enabled user."""
    log.info("auto-apply poller started (tick=%ds)", TICK_SECONDS)
    while True:
        try:
            await _tick_all()
        except Exception:  # pragma: no cover
            log.exception("auto-apply poller: tick raised unexpectedly")
        await asyncio.sleep(TICK_SECONDS)
