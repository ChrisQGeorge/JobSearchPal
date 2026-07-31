"""Background worker that processes the generalized Companion task queue.

The table is still named `job_fetch_queue` for historical reasons, but after
migration 0012 it carries tasks of any kind — fetch, score, tailor, humanize,
interview_prep, etc. Each row has a `kind` column; this worker dispatches to
a kind-specific handler.

Runs as a single asyncio task launched from the FastAPI lifespan, polls the
queue every few seconds, claims one row at a time with state=queued, runs
the handler, and marks the row done/error. Bounded retries.

Design notes:
  * Single-worker, single-container — no distributed locking needed. A
    simple UPDATE … WHERE state='queued' claim step handles the race
    between claim-and-process, which matters only if multiple workers ever
    run at once.
  * Serialization is the point: Claude CLI rate limits + cost mean parallel
    parallel calls backfire. One task at a time, FIFO by id.
  * Rate-limit cooldowns are transparent to the caller — the task bounces
    back to `queued` with a future `resume_after`; attempts aren't burned.
  * Stuck "processing" rows older than STUCK_RESET_MINUTES get reset to
    "queued" at startup so a crashed previous run doesn't leave holes.
  * Attempts are capped at MAX_ATTEMPTS. The UI's retry button resets to 0.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from datetime import datetime, time as _dt_time, timedelta, timezone

from sqlalchemy import and_, delete as sa_delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.jobs import JobFetchQueue, TrackedJob

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
STUCK_RESET_MINUTES = 20
MAX_ATTEMPTS = 3
# Finished rows are kept for a while as history on the /queue page, then
# pruned so the table doesn't grow forever — the activity endpoints pay
# per-row on every poll, and a bulk import can add thousands of rows.
# Errors are kept longer so the user has time to notice and retry them.
PRUNE_DONE_AFTER_DAYS = 7
PRUNE_ERROR_AFTER_DAYS = 30
PRUNE_INTERVAL_SECONDS = 24 * 3600
# Every `claude -p` run leaves a session transcript (embedding the full
# page text / JD from the prompt) plus todo/snapshot files under
# CLAUDE_CONFIG_DIR. A bulk import means thousands of runs — the config
# volume grows without bound and the CLI's per-spawn startup cost creeps
# up with it. Prune byproduct files older than this.
PRUNE_CLAUDE_FILES_AFTER_DAYS = 7
_CLAUDE_BYPRODUCT_DIRS = ("projects", "todos", "shell-snapshots", "session-env")

# Substrings that indicate the CLI hit an Anthropic rate-limit / usage-cap
# rather than a regular failure. We treat these as "try again later" and
# don't burn retry attempts on them.
_RATE_LIMIT_PATTERNS = (
    "usage limit",
    "usage_limit_error",
    "rate limit",
    "rate_limit_error",
    "rate-limit",
    "too many requests",
    "overloaded_error",
    "overloaded",
    " 429",
    "retry after",
    "quota exceeded",
    "limit reached",
    "claude pro usage",
    "pro usage",
    "max usage",
    "session limit",
    "weekly limit",
    "daily limit",
    "try again at",
    "reset at",
    "will reset",
)

# Cooldown schedule for repeated rate-limit hits on a single row without an
# explicit retry-after hint. Starts at 10 min; the last step corresponds to
# Claude Pro's typical 5-hour usage-window reset. Cap is 6 hours so a user
# can pay back Claude's weekly cap by just leaving the container running.
_COOLDOWN_MINUTES = (10, 30, 60, 120, 180, 300)
# Hard ceiling on any single cooldown, even if the server hints longer. 12h
# is enough for a usage reset to tick over; after that we'd rather retry and
# re-capture a fresh hint than park a task indefinitely.
_MAX_COOLDOWN_SECONDS = 12 * 3600
# Safety margin added to server-hinted retry-after so we don't slam the API
# the instant the window opens.
_HINT_SAFETY_SECONDS = 30

# Patterns below are tried in order; the FIRST hit wins. Each returns a
# seconds-from-now duration.
_UNIT_SECONDS = {
    "second": 1, "sec": 1, "s": 1,
    "minute": 60, "min": 60, "m": 60,
    "hour": 3600, "hr": 3600, "h": 3600,
}


def _is_rate_limited(msg: str) -> bool:
    low = (msg or "").lower()
    return any(pat in low for pat in _RATE_LIMIT_PATTERNS)


def _parse_hhmm(token: str) -> _dt_time | None:
    """Parse '3 PM', '3:00pm', '15:00', '3am' into a 24h time. UTC-ish — we
    don't know Claude's server timezone, so we just treat the hour as whatever
    clock the user sees. The user's host timezone is used as best-effort.
    """
    token = token.strip().lower().replace(" ", "")
    m = re.match(r"(\d{1,2})(?::(\d{2}))?(am|pm)?$", token)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return _dt_time(hour=hour, minute=minute)


def _seconds_until_local(target: _dt_time) -> int:
    """Seconds from now until the next occurrence of `target` in local
    wallclock. If `target` is already past today, returns the delay until
    tomorrow at that time."""
    now_local = datetime.now().astimezone()
    today_target = now_local.replace(
        hour=target.hour, minute=target.minute, second=0, microsecond=0
    )
    if today_target <= now_local:
        today_target = today_target + timedelta(days=1)
    delta = today_target - now_local
    return max(0, int(delta.total_seconds()))


def _rate_limit_retry_seconds(msg: str) -> int | None:
    """Extract an explicit retry-after delay if the error message carries
    one. Understands:

      * "retry after 600 seconds" / "try again in 15 minutes" / "in 5 h"
      * "usage resets at 3:00 PM" / "reset at 15:00" / "will reset at 9am"
      * "Retry-After: 600"  (seconds, HTTP header passthrough)

    Returns seconds-from-now, or None if no hint is present."""
    if not msg:
        return None
    low = msg.lower()

    # --- Clock-time form: "reset at 3:00 PM", "resets at 15:00" ----------
    # This is the common shape from Claude Pro usage-cap messages.
    m = re.search(
        r"(?:reset|resets|reset at|resets at|resume|resumes|available|refresh(?:es)?|try again)"
        r"(?:\s+(?:at|around|by))?"
        r"\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
        low,
    )
    if m:
        t = _parse_hhmm(m.group(1))
        if t is not None:
            secs = _seconds_until_local(t)
            if 60 <= secs <= _MAX_COOLDOWN_SECONDS:
                return secs

    # --- Duration form: "in 5 hours", "retry after 600 seconds", "in 30m" -
    dur = re.search(
        r"(?:retry(?:-|\s)?after|try again in|in|resumes in|resets in|for)\s+"
        r"(\d{1,6})\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b",
        low,
    )
    if dur:
        qty = int(dur.group(1))
        unit = dur.group(2).rstrip(".").rstrip("s") or "s"
        mult = _UNIT_SECONDS.get(unit, 1)
        return qty * mult

    # --- Bare HTTP Retry-After header leaked into the message ------------
    m = re.search(r"retry-?after[:\s]+(\d{1,6})", low)
    if m:
        return int(m.group(1))

    # --- Last-resort duration match (legacy behavior) --------------------
    m = re.search(r"\b(\d{1,6})\s*(seconds?|secs?|s)\b", low)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,4})\s*(minutes?|mins?|m)\b", low)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"\b(\d{1,3})\s*(hours?|hrs?|h)\b", low)
    if m:
        return int(m.group(1)) * 3600
    return None


async def _reset_stuck_rows() -> None:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=STUCK_RESET_MINUTES)
    async with SessionLocal() as db:
        stmt = (
            update(JobFetchQueue)
            .where(
                and_(
                    JobFetchQueue.state == "processing",
                    JobFetchQueue.last_attempt_at < cutoff,
                )
            )
            .values(state="queued")
        )
        result = await db.execute(stmt)
        await db.commit()
        if result.rowcount:
            log.info(
                "Queue worker reset %d stuck processing row(s) older than %d min",
                result.rowcount,
                STUCK_RESET_MINUTES,
            )


async def _prune_old_rows() -> None:
    """Delete long-finished queue rows (done > 7 days, error > 30 days,
    by last activity). Runs at boot and then daily from the main loop."""
    now = datetime.now(tz=timezone.utc)
    async with SessionLocal() as db:
        for state, days in (
            ("done", PRUNE_DONE_AFTER_DAYS),
            ("error", PRUNE_ERROR_AFTER_DAYS),
        ):
            cutoff = now - timedelta(days=days)
            result = await db.execute(
                sa_delete(JobFetchQueue).where(
                    JobFetchQueue.state == state,
                    func.coalesce(
                        JobFetchQueue.last_attempt_at, JobFetchQueue.created_at
                    )
                    < cutoff,
                )
            )
            if result.rowcount:
                log.info(
                    "Queue worker pruned %d '%s' row(s) older than %d day(s)",
                    result.rowcount, state, days,
                )
        await db.commit()


def _prune_claude_byproducts_sync() -> tuple[int, int]:
    """Delete Claude CLI byproduct files older than
    PRUNE_CLAUDE_FILES_AFTER_DAYS under CLAUDE_CONFIG_DIR. Returns
    (files_removed, bytes_freed). Sync — run via asyncio.to_thread.
    Age-based (mtime), so anything a live `claude` process is still
    touching is never in scope."""
    import os
    import time
    from pathlib import Path

    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR", "/root/.claude"))
    cutoff = time.time() - PRUNE_CLAUDE_FILES_AFTER_DAYS * 86400
    removed = 0
    freed = 0
    for sub in _CLAUDE_BYPRODUCT_DIRS:
        root = cfg / sub
        if not root.is_dir():
            continue
        dirs: list[Path] = []
        for p in root.rglob("*"):
            try:
                if p.is_dir():
                    dirs.append(p)
                elif p.is_file() and p.stat().st_mtime < cutoff:
                    size = p.stat().st_size
                    p.unlink()
                    removed += 1
                    freed += size
            except OSError:
                continue
        # Sweep now-empty per-project subdirs, deepest first. rmdir
        # refuses non-empty dirs, so this can't eat anything live.
        for d in sorted(dirs, key=lambda d: len(str(d)), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
    return removed, freed


def _ensure_claude_cleanup_setting() -> None:
    """Make the Claude CLI prune its own chat transcripts by setting
    `cleanupPeriodDays` in CLAUDE_CONFIG_DIR/settings.json (only when the
    user hasn't already set a value). Belt to the braces above — the CLI
    cleans on its own startup; our sweep catches whatever it misses."""
    import json
    import os
    from pathlib import Path

    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR", "/root/.claude"))
    path = cfg / "settings.json"
    try:
        data: dict = {}
        if path.exists():
            loaded = json.loads(path.read_text() or "{}")
            if isinstance(loaded, dict):
                data = loaded
        if "cleanupPeriodDays" not in data:
            data["cleanupPeriodDays"] = PRUNE_CLAUDE_FILES_AFTER_DAYS
            cfg.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
            log.info(
                "Set cleanupPeriodDays=%d in %s",
                PRUNE_CLAUDE_FILES_AFTER_DAYS, path,
            )
    except (OSError, json.JSONDecodeError):
        log.warning("Could not ensure Claude cleanupPeriodDays setting", exc_info=True)


async def _claim_next(db: AsyncSession) -> JobFetchQueue | None:
    """Pick the oldest queued row and mark it processing atomically.

    Rows with a future `resume_after` are skipped — that's our rate-limit
    cooldown. They get picked up automatically once the timestamp passes.
    """
    now = datetime.now(tz=timezone.utc)
    stmt = (
        select(JobFetchQueue)
        .where(
            JobFetchQueue.state == "queued",
            or_(
                JobFetchQueue.resume_after.is_(None),
                JobFetchQueue.resume_after <= now,
            ),
        )
        .order_by(JobFetchQueue.id.asc())
        .limit(1)
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        return None
    item.state = "processing"
    item.attempts = (item.attempts or 0) + 1
    item.last_attempt_at = datetime.now(tz=timezone.utc)
    item.error_message = None
    await db.commit()
    await db.refresh(item)
    return item


async def _handle_rate_limit(
    db: AsyncSession, row: JobFetchQueue, err: str
) -> None:
    """Common cooldown logic used by every handler. Rolls the row back to
    queued with a future resume_after and doesn't burn the attempt.

    Also propagates the cooldown to every other queued task owned by the
    same user. Reason: rate-limits are account-scoped, not row-scoped —
    if we don't pause the whole queue, the worker will immediately claim
    the next row, burn through a wasted claim + Claude subprocess spawn,
    and re-hit the same error. Propagating is conservative: we only push
    `resume_after` *forward*, never pull it back, so tasks already in a
    longer cooldown stay there."""
    # Track consecutive rate-limit hits in `payload.rate_limit_count` so the
    # escalating cooldown schedule works independently of `attempts` (which
    # we roll back on rate-limits so a genuinely stuck task can still
    # eventually transition to "error"). Clears on successful run.
    payload = dict(row.payload or {})
    rl_count = int(payload.get("rate_limit_count") or 0)
    hinted = _rate_limit_retry_seconds(err)
    if hinted and hinted > 0:
        cooldown_s = min(hinted + _HINT_SAFETY_SECONDS, _MAX_COOLDOWN_SECONDS)
    else:
        idx = min(rl_count, len(_COOLDOWN_MINUTES) - 1)
        cooldown_s = _COOLDOWN_MINUTES[idx] * 60
    resume_at = datetime.now(tz=timezone.utc) + timedelta(seconds=cooldown_s)

    payload["rate_limit_count"] = rl_count + 1
    row.payload = payload
    row.attempts = max(0, (row.attempts or 0) - 1)
    row.state = "queued"
    row.resume_after = resume_at
    row.error_message = (
        f"Rate-limited — resuming at {resume_at.isoformat(timespec='minutes')} "
        f"(cooldown {cooldown_s // 60}m, hit #{rl_count + 1}). "
        f"({err.strip().splitlines()[0][:160]})"
    )
    await db.commit()

    # Propagate to siblings owned by the same user so the worker doesn't
    # burn the next 49 rows on the same usage-cap. Only push resume_after
    # forward — rows already in a longer cooldown keep theirs.
    sibling_stmt = (
        update(JobFetchQueue)
        .where(
            JobFetchQueue.user_id == row.user_id,
            JobFetchQueue.id != row.id,
            JobFetchQueue.state == "queued",
            or_(
                JobFetchQueue.resume_after.is_(None),
                JobFetchQueue.resume_after < resume_at,
            ),
        )
        .values(resume_after=resume_at)
    )
    sibling_result = await db.execute(sibling_stmt)
    await db.commit()

    log.info(
        "Queue item %d (%s) rate-limited; cooldown %ds → resume_after=%s. "
        "Propagated cooldown to %d sibling task(s).",
        row.id,
        row.kind or "fetch",
        cooldown_s,
        resume_at.isoformat(),
        sibling_result.rowcount or 0,
    )


async def _fail(
    db: AsyncSession,
    row: JobFetchQueue,
    err: str,
    *,
    permanent: bool = False,
) -> None:
    """Mark a row errored. By default re-queues until attempts hit
    MAX_ATTEMPTS. Pass `permanent=True` to bail after the first
    attempt — used by handlers (like the JD analyzer) where retrying
    a bad input usually just costs more Claude turns to reach the
    same failure."""
    row.state = "error" if (permanent or row.attempts >= MAX_ATTEMPTS) else "queued"
    row.error_message = err
    await db.commit()
    log.warning(
        "Queue item %d (%s) failed (attempt %d%s): %s",
        row.id,
        row.kind or "fetch",
        row.attempts,
        " — permanent" if permanent else "",
        err,
    )


async def _enqueue_followups(
    db: "AsyncSession",
    tj: "TrackedJob",
    *,
    label_prefix: str = "",
) -> None:
    """After a fetch lands a TrackedJob, queue the JD-score Companion
    task. The heavier follow-ups (company research + application prep)
    are deferred — they only fire when the user moves the row to
    `interested` (see `enqueue_interested_followups` below), so they
    don't run on every fetched row the user might just want to triage
    and discard. Caller is responsible for the surrounding commit."""
    from app.models.jobs import JobFetchQueue

    if tj.job_description and tj.job_description.strip():
        db.add(
            JobFetchQueue(
                user_id=tj.user_id,
                kind="score",
                label=f"{label_prefix}Score → {tj.title[:80]}"[:512],
                url="",
                payload={"tracked_job_id": tj.id},
                state="queued",
            )
        )


async def enqueue_interested_followups(
    db: "AsyncSession",
    tj: "TrackedJob",
    *,
    label_prefix: str = "",
    force_prep: bool = False,
) -> None:
    """Fired when a TrackedJob moves to `interested`. Queues:

      - org_research — only when the org isn't already enriched
        (description + industry filled).
      - prep — generates resume_emphasis / cover_letter_hook /
        interview_focus_areas hints. Only on the FIRST flip to
        interested. The presence of an existing prep row (any state,
        ever) suppresses re-queueing so the user toggling away and
        back doesn't burn Claude budget. Pass `force_prep=True` to
        bypass the guard — used by the explicit "Regenerate prep"
        button on the job detail page.

    Best-effort: missing org_id / missing description → skip the
    respective task silently. Caller commits."""
    from app.models.jobs import JobFetchQueue, Organization
    from sqlalchemy import select

    if not tj.organization_id:
        log.info(
            "enqueue_interested_followups: tracked_job %d has no "
            "organization_id, skipping org_research",
            tj.id,
        )
    else:
        org = (
            await db.execute(
                select(Organization).where(
                    Organization.id == tj.organization_id,
                    Organization.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if org is None:
            log.info(
                "enqueue_interested_followups: org %s for tracked_job "
                "%d not found / soft-deleted, skipping org_research",
                tj.organization_id, tj.id,
            )
        else:
            # `research_notes` is populated only by the research pipeline
            # (users typically don't fill it manually). Using it as the
            # signal means: if the org has been researched ONCE — even if
            # some specific column came back null from that pass — we
            # don't re-fire. Previous check required both description AND
            # industry, which was too eager: an org with description but
            # null industry kept getting re-researched on every interested
            # flip across multiple jobs at the same company.
            already_researched = bool((org.research_notes or "").strip())
            if already_researched:
                log.info(
                    "enqueue_interested_followups: org %d (%s) already "
                    "has research_notes, skipping org_research",
                    org.id, org.name,
                )
            else:
                db.add(
                    JobFetchQueue(
                        user_id=tj.user_id,
                        kind="org_research",
                        label=f"{label_prefix}Research: {org.name}"[:512],
                        url="",
                        payload={"organization_id": org.id},
                        state="queued",
                    )
                )
                log.info(
                    "enqueue_interested_followups: queued org_research "
                    "for org %d (%s) on behalf of tracked_job %d",
                    org.id, org.name, tj.id,
                )

    if tj.job_description and tj.job_description.strip():
        # First-flip-only: never re-fire automatically. The user
        # presses "Regenerate prep" if they want a fresh pass.
        already = False
        if not force_prep:
            existing_rows = (
                await db.execute(
                    select(JobFetchQueue).where(
                        JobFetchQueue.user_id == tj.user_id,
                        JobFetchQueue.kind == "prep",
                    )
                )
            ).scalars().all()
            for r in existing_rows:
                if isinstance(r.payload, dict) and r.payload.get("tracked_job_id") == tj.id:
                    already = True
                    break
        if not already:
            db.add(
                JobFetchQueue(
                    user_id=tj.user_id,
                    kind="prep",
                    label=f"{label_prefix}Prep → {tj.title[:80]}"[:512],
                    url="",
                    payload={"tracked_job_id": tj.id},
                    state="queued",
                )
            )


async def cancel_pending_tasks_for_job(
    db: "AsyncSession",
    tj: "TrackedJob",
    *,
    kinds: tuple[str, ...] = ("score", "prep"),
) -> int:
    """Drop still-queued Companion tasks that target `tj` — fired when the
    user flips a job to `not_interested`, where scoring/prep would just
    burn Claude budget on a job they've already ruled out. Only `queued`
    rows are touched: a `processing` row already has a live Claude
    subprocess, and its handler re-reads + commits the row when it lands,
    so deleting it mid-flight would resurrect or orphan the work anyway.
    Returns the number of rows dropped. Caller commits."""
    rows = (
        await db.execute(
            select(JobFetchQueue).where(
                JobFetchQueue.user_id == tj.user_id,
                JobFetchQueue.state == "queued",
                JobFetchQueue.kind.in_(kinds),
            )
        )
    ).scalars().all()
    dropped = 0
    for r in rows:
        if isinstance(r.payload, dict) and r.payload.get("tracked_job_id") == tj.id:
            await db.delete(r)
            dropped += 1
    if dropped:
        log.info(
            "Cancelled %d pending %s task(s) for TrackedJob %d (not interested)",
            dropped, "/".join(kinds), tj.id,
        )
    return dropped


async def _handle_fetch(item: JobFetchQueue) -> None:
    """Claim-a-URL → fetch → create OR enrich a TrackedJob.

    Two modes:
    - Default ("create"): inserts a new TrackedJob from the fetched
      fields. Used by the URL-paste flow on the tracker.
    - Enrich ("update existing"): when payload carries
      `{"tracked_job_id": N}`, the handler updates that row instead of
      creating a new one. Only fills in fields that are currently
      empty on the row, so user-edited values are never trampled.
      Used by lead promotion — the lead seeded the row from the
      cached body; the fetch then upgrades it with the
      organization-context + skill-list extraction the URL flow does.
    """
    from app.api.v1.jobs import build_tracked_job_payload, perform_fetch
    from app.skills.runner import ClaudeCodeError
    from app.skills import queue_bus

    # Phase 1: read the queue row state. Session held briefly.
    async with SessionLocal() as db:
        row = (
            await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
        ).scalar_one_or_none()
        if row is None:
            return
        item_id = row.id
        item_url = row.url
        label = row.label or row.url or f"Fetch #{row.id}"
        existing_job_id: Optional[int] = None
        if isinstance(row.payload, dict):
            tj_id = row.payload.get("tracked_job_id")
            if isinstance(tj_id, int):
                existing_job_id = tj_id
        row_url = row.url

    def _on_event(ev: dict) -> None:
        p = dict(ev)
        p.setdefault("item_id", f"queue:{item_id}")
        p.setdefault("source", "fetch")
        p.setdefault("label", label)
        p.setdefault("url", item_url)
        queue_bus.publish(p)

    queue_bus.publish({
        "item_id": f"queue:{item_id}", "source": "fetch",
        "label": label, "url": item_url, "kind": "start",
    })

    # Phase 2: long Claude call. NO session held — perform_fetch now
    # manages its own session internally for the org-resolution write.
    try:
        fetched = await perform_fetch(None, row_url, on_event=_on_event)
    except ClaudeCodeError as exc:
        err = str(exc)
        async with SessionLocal() as db:
            row = (
                await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
            ).scalar_one_or_none()
            if row is None:
                return
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err)
        return
    except Exception as exc:  # pragma: no cover
        async with SessionLocal() as db:
            row = (
                await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
            ).scalar_one_or_none()
            if row is not None:
                await _fail(db, row, f"Unexpected error: {exc}")
        log.exception("Fetch task %d unhandled error", item.id)
        return

    # Phase 3: writes. Fresh session.
    async with SessionLocal() as db:
        row = (
            await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
        ).scalar_one_or_none()
        if row is None:
            return

        if fetched.warning:
            row.state = "error"
            row.error_message = fetched.warning
            await db.commit()
            return

        overrides: dict = {}
        if row.desired_status: overrides["status"] = row.desired_status
        if row.desired_priority: overrides["priority"] = row.desired_priority
        if row.desired_date_applied: overrides["date_applied"] = row.desired_date_applied
        if row.desired_date_closed: overrides["date_closed"] = row.desired_date_closed
        if row.desired_date_posted: overrides["date_posted"] = row.desired_date_posted
        if row.desired_notes: overrides["notes"] = row.desired_notes
        payload = build_tracked_job_payload(fetched, overrides=overrides)

        from app.models.jobs import ApplicationEvent

        if existing_job_id is not None:
            # Enrich path — update an existing row. Only overwrite
            # fields that are currently empty so user / lead-seed
            # values aren't trampled.
            existing = (
                await db.execute(
                    select(TrackedJob).where(
                        TrackedJob.id == existing_job_id,
                        TrackedJob.user_id == row.user_id,
                        TrackedJob.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                # Row was deleted out from under us — fall back to create.
                existing_job_id = None
            else:
                changed = []
                # Drop status from overrides — never overwrite the
                # user's chosen lead-promotion target with the URL's
                # default. Same for priority / date_applied if the
                # promote path didn't set them.
                payload.pop("status", None)
                for field, value in payload.items():
                    if value is None or value == "" or value == []:
                        continue
                    current = getattr(existing, field, None)
                    if current is None or current == "" or current == []:
                        setattr(existing, field, value)
                        changed.append(field)
                if changed:
                    db.add(
                        ApplicationEvent(
                            tracked_job_id=existing.id,
                            event_type="note",
                            event_date=datetime.now(tz=timezone.utc),
                            details_md=(
                                f"Enriched from fetch-queue URL `{row.url}` — "
                                f"filled {', '.join(changed)}."
                            ),
                        )
                    )
                row.state = "done"
                row.created_tracked_job_id = existing.id
                row.result = {
                    "created_tracked_job_id": existing.id,
                    "mode": "enriched",
                    "fields_filled": changed,
                }
                row.error_message = None
                # Auto-queue JD-analyze + org_research if the
                # enrichment filled new fields. Skipped silently when
                # there's nothing to score or the org's already
                # researched.
                await _enqueue_followups(db, existing)
                await db.commit()
                queue_bus.publish({
                    "item_id": f"queue:{item_id}", "source": "fetch",
                    "label": label, "url": item_url, "kind": "done",
                    "created_tracked_job_id": existing.id,
                })
                log.info(
                    "Fetch task %d → enriched TrackedJob id=%d (filled %d fields)",
                    row.id, existing.id, len(changed),
                )
                return

        # Same-URL dedup. If the user already has a non-deleted TrackedJob
        # for this URL, skip the import entirely — don't create a duplicate
        # row and don't touch the existing one. Back-link any originating
        # lead onto the existing job so the leads inbox still reflects
        # "this lead is tracked" rather than "still a lead".
        from app.api.v1.jobs import _find_existing_job_by_url

        dup_lead_id: Optional[int] = None
        if isinstance(row.payload, dict):
            lid = row.payload.get("lead_id")
            if isinstance(lid, int):
                dup_lead_id = lid

        duplicate = await _find_existing_job_by_url(db, row.user_id, payload.get("source_url") or row.url)
        if duplicate is not None:
            if dup_lead_id is not None:
                from app.models.sources import JobLead

                lead = (
                    await db.execute(
                        select(JobLead).where(
                            JobLead.id == dup_lead_id,
                            JobLead.user_id == row.user_id,
                        )
                    )
                ).scalar_one_or_none()
                if lead is not None:
                    lead.tracked_job_id = duplicate.id

            row.state = "done"
            row.created_tracked_job_id = duplicate.id
            row.result = {
                "created_tracked_job_id": duplicate.id,
                "mode": "duplicate",
                "note": "URL already tracked — import skipped, existing row left untouched.",
            }
            row.error_message = None
            await db.commit()
            queue_bus.publish({
                "item_id": f"queue:{item_id}", "source": "fetch",
                "label": label, "url": item_url, "kind": "done",
                "created_tracked_job_id": duplicate.id,
                "mode": "duplicate",
            })
            log.info(
                "Fetch task %d → duplicate of TrackedJob id=%d, skipped import",
                row.id, duplicate.id,
            )
            return

        # Create path (default).
        job = TrackedJob(user_id=row.user_id, **payload)
        db.add(job)
        await db.flush()

        # If this fetch was triggered by a lead promotion, back-link
        # the new TrackedJob onto the originating JobLead row so the
        # leads inbox reflects the promotion target.
        lead_id: Optional[int] = dup_lead_id
        if lead_id is not None:
            from app.models.sources import JobLead

            lead = (
                await db.execute(
                    select(JobLead).where(
                        JobLead.id == lead_id,
                        JobLead.user_id == row.user_id,
                    )
                )
            ).scalar_one_or_none()
            if lead is not None:
                lead.tracked_job_id = job.id

        db.add(ApplicationEvent(
            tracked_job_id=job.id,
            event_type="note",
            event_date=datetime.now(tz=timezone.utc),
            details_md=(
                f"Created from lead → fetched `{row.url}`."
                if lead_id is not None
                else f"Created from fetch-queue URL `{row.url}`."
            ),
        ))

        row.state = "done"
        row.created_tracked_job_id = job.id
        row.result = {"created_tracked_job_id": job.id}
        row.error_message = None
        # Clear any rate_limit_count from prior cooldown attempts so this
        # row, if somehow re-run later (via Retry), starts fresh.
        if isinstance(row.payload, dict) and "rate_limit_count" in row.payload:
            new_payload = dict(row.payload)
            new_payload.pop("rate_limit_count", None)
            row.payload = new_payload or None
        # Auto-queue JD-analyze + company-research so the new row
        # lands fully enriched without the user clicking Score / Research.
        await _enqueue_followups(db, job)
        await db.commit()
        queue_bus.publish({
            "item_id": f"queue:{item_id}", "source": "fetch",
            "label": label, "url": item_url, "kind": "done",
            "created_tracked_job_id": job.id,
        })
        log.info("Fetch task %d → created TrackedJob id=%d", row.id, job.id)


async def _handle_score(item: JobFetchQueue) -> None:
    """Run the JD analyzer against the tracked_job_id in payload. Persists
    jd_analysis and fit_summary on the TrackedJob row."""
    from app.skills.runner import ClaudeCodeError
    from app.skills import queue_bus

    async with SessionLocal() as db:
        row = (
            await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
        ).scalar_one_or_none()
        if row is None:
            return
        payload = row.payload or {}
        tracked_job_id = payload.get("tracked_job_id")
        if not tracked_job_id:
            await _fail(db, row, "score task missing tracked_job_id", permanent=True)
            return

        job = (
            await db.execute(
                select(TrackedJob).where(
                    TrackedJob.id == tracked_job_id,
                    TrackedJob.user_id == row.user_id,
                    TrackedJob.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if job is None:
            await _fail(db, row, f"TrackedJob {tracked_job_id} not found", permanent=True)
            return
        if not (job.job_description and job.job_description.strip()):
            await _fail(db, row, "job has no description to analyze", permanent=True)
            return

        # Import the prompt + JD analyzer helpers from the jobs router.
        from app.api.v1.jobs import (
            _build_jd_analyze_prompt,
            _extract_json_object,
            _apply_jd_analysis_to_job,
        )
        prompt = _build_jd_analyze_prompt(job)

        from app.core.security import create_access_token
        api_token = create_access_token(
            subject=str(row.user_id), extra={"purpose": "jd_analyzer"}
        )

        label = row.label or f"Score: {job.title}"
        try:
            # item_id = f"queue:{row.id}" is the canonical convention for any
            # bus event sourced from a DB task row. `_fetch_queue_to_row`
            # uses the same key to merge live progress into the DB row so
            # the UI shows one row per task, not two.
            final_text = await queue_bus.run_claude_to_bus(
                prompt=prompt,
                source="jd_analyze",
                item_id=f"queue:{row.id}",
                label=label,
                allowed_tools=["Bash"],
                extra_env={
                    "JSP_API_BASE_URL": "http://localhost:8000",
                    "JSP_API_TOKEN": api_token,
                },
                timeout_seconds=180,
                action="jd_analyze",
            )
        except ClaudeCodeError as exc:
            err = str(exc)
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err, permanent=True)
            return
        except Exception as exc:  # pragma: no cover
            await _fail(db, row, f"Unexpected error: {exc}", permanent=True)
            log.exception("Score task %d unhandled error", row.id)
            return

        data = _extract_json_object(final_text) or {}
        if not data:
            # A usage/rate-limit cap is delivered by the CLI as a normal
            # exit-0 result ("You've hit your session limit · resets 5:50pm"),
            # NOT a non-zero exit — so it slips past the except-ClaudeCodeError
            # branch above and lands here. Detect it on the success path too
            # and PARK the task (cooldown + auto-resume) instead of burning it
            # as a permanent failure.
            if _is_rate_limited(final_text):
                await _handle_rate_limit(db, row, final_text)
                return
            # Include a snippet of what Claude actually returned so the
            # user can see whether it's hitting a rate-limit message, a
            # tool error, or just emitting prose instead of JSON.
            snippet = (final_text or "").strip()
            if len(snippet) > 600:
                snippet = snippet[:300] + " […] " + snippet[-300:]
            await _fail(
                db, row,
                "JD analyzer returned no parseable JSON. "
                f"Raw Claude output (truncated): {snippet!r}",
                permanent=True,
            )
            return
        _apply_jd_analysis_to_job(job, data)

        # JD analysis usually populates required_skills / nice_to_have_skills
        # which the deterministic scorer reads. Recompute fit_score
        # automatically so the user doesn't have to click Score again
        # after the analyzer finishes. Mirror what the foreground
        # /analyze-jd endpoint does. Best-effort: a failure here
        # shouldn't fail the whole score task — the JD analysis is
        # still useful even without an updated numeric fit_score.
        try:
            from app.scoring.fit import apply_fit_score_to_job, compute_fit_score
            from app.models.user import User as _User

            user = (
                await db.execute(select(_User).where(_User.id == row.user_id))
            ).scalar_one_or_none()
            if user is not None:
                fit_result = await compute_fit_score(db, user, job)
                apply_fit_score_to_job(job, fit_result)
        except Exception as exc:  # pragma: no cover
            log.warning(
                "Score task %d: jd_analysis persisted but fit-score recompute "
                "failed: %s",
                row.id, exc,
            )

        row.state = "done"
        row.result = {
            "tracked_job_id": job.id,
            "fit_score": (
                job.fit_summary.get("score")
                if isinstance(job.fit_summary, dict)
                else None
            ),
        }
        row.error_message = None
        if isinstance(row.payload, dict) and "rate_limit_count" in row.payload:
            new_payload = dict(row.payload)
            new_payload.pop("rate_limit_count", None)
            row.payload = new_payload or None
        await db.commit()
        log.info(
            "Score task %d → applied jd_analysis + fit_score to TrackedJob %d",
            row.id, job.id,
        )


async def _mark_doc(
    doc_id: int,
    *,
    content_md: str | None = None,
    title: str | None = None,
    structured: dict | None = None,
) -> None:
    """Update a GeneratedDocument row after a queued tailor/humanize run."""
    from app.models.documents import GeneratedDocument as _GD

    async with SessionLocal() as db:
        doc = (
            await db.execute(select(_GD).where(_GD.id == doc_id))
        ).scalar_one_or_none()
        if doc is None:
            return
        if content_md is not None:
            doc.content_md = content_md
        if title is not None:
            doc.title = title[:255]
        if structured is not None:
            doc.content_structured = structured
        await db.commit()


async def _handle_tailor(item: JobFetchQueue) -> None:
    """Run a tailor prompt (resume / cover letter / email / generic) and
    update the placeholder GeneratedDocument with the result. Payload:
      - generated_document_id: int
      - prompt: str (already-escaped, ready for Claude)
      - doc_type: str
      - title_override: str | None
      - job_title: str  (for the default title and bus label)
    Rate limits are handled by the shared `_handle_rate_limit` so the
    task parks and auto-resumes when the window opens.
    """
    from datetime import datetime as _dt, timezone as _tz
    from app.core.security import create_access_token
    from app.skills.runner import ClaudeCodeError
    from app.skills import queue_bus

    async with SessionLocal() as db:
        row = (
            await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
        ).scalar_one_or_none()
        if row is None:
            return
        payload = row.payload or {}
        doc_id = payload.get("generated_document_id")
        prompt = payload.get("prompt")
        doc_type = payload.get("doc_type", "other")
        title_override = payload.get("title_override")
        job_title = payload.get("job_title") or "job"
        if not doc_id or not prompt:
            await _fail(db, row, "tailor task missing doc_id or prompt")
            return

        api_token = create_access_token(
            subject=str(row.user_id), extra={"purpose": f"doc_tailor_{doc_type}"}
        )
        label = row.label or f"{doc_type.replace('_', ' ').title()}: {job_title}"

        # Map doc_type to a model-settings action key. resume / cover
        # letter get dedicated knobs; everything else (outreach, follow-up,
        # custom) shares one bucket.
        _tailor_action = (
            "tailor_resume" if doc_type == "resume"
            else "tailor_cover_letter" if doc_type == "cover_letter"
            else "tailor_other"
        )
        try:
            final_text = await queue_bus.run_claude_to_bus(
                prompt=prompt,
                source=f"tailor_{doc_type}",
                item_id=f"queue:{row.id}",
                label=label,
                allowed_tools=["Bash"],
                timeout_seconds=600,
                action=_tailor_action,
                extra_env={
                    "JSP_API_BASE_URL": "http://localhost:8000",
                    "JSP_API_TOKEN": api_token,
                },
            )
        except ClaudeCodeError as exc:
            err = str(exc)
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err)
            await _mark_doc(
                doc_id,
                structured={
                    "status": "error",
                    "finished_at": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
                    "error": f"Claude Code error: {exc}",
                },
            )
            return
        except Exception as exc:  # pragma: no cover
            await _fail(db, row, f"Unexpected error: {exc}")
            await _mark_doc(
                doc_id,
                structured={
                    "status": "error",
                    "finished_at": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
                    "error": f"Unexpected error: {exc}",
                },
            )
            log.exception("Tailor task %d unhandled error", row.id)
            return

        # Parse and apply. Defer the import so queue_worker stays importable
        # without pulling all of documents.py.
        from app.api.v1.documents import _extract_json_object

        data = _extract_json_object(final_text) or {}
        content_md = (data.get("content_md") or "").strip()
        if not content_md:
            # Usage-cap message comes back as a successful (exit-0) result,
            # not a ClaudeCodeError — so catch it here and park for cooldown
            # rather than burning the doc as errored + retrying 3× into the
            # same cap. The placeholder stays in its "generating" state and
            # the task auto-resumes when the window reopens.
            if _is_rate_limited(final_text):
                await _handle_rate_limit(db, row, final_text)
                return
            msg = "Tailoring returned no content."
            await _fail(db, row, msg)
            await _mark_doc(
                doc_id,
                structured={
                    "status": "error",
                    "finished_at": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
                    "error": msg,
                },
            )
            return

        title = (
            title_override
            or data.get("title")
            or f"{doc_type.replace('_', ' ').title()} – {job_title}"
        )
        await _mark_doc(
            doc_id,
            content_md=content_md,
            title=title,
            structured={
                "status": "ready",
                "finished_at": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
                "notes": data.get("notes"),
                "warning": data.get("warning"),
                "error": None,
            },
        )

        row.state = "done"
        row.result = {"generated_document_id": doc_id}
        row.error_message = None
        if isinstance(row.payload, dict) and "rate_limit_count" in row.payload:
            new_payload = dict(row.payload)
            new_payload.pop("rate_limit_count", None)
            row.payload = new_payload or None
        await db.commit()
        log.info("Tailor task %d → updated GeneratedDocument %d", row.id, doc_id)


async def _handle_humanize(item: JobFetchQueue) -> None:
    """Run the humanizer's main prompt + any AI-tell fix-passes and update
    the placeholder GeneratedDocument. Payload:
      - generated_document_id: int
      - prompt: str
      - source_doc_id: int
      - source_title: str
      - source_body: str  (raw source, used by the banned-phrase validator)
      - plant_mistakes: bool
    """
    from datetime import datetime as _dt, timezone as _tz
    from app.skills.runner import ClaudeCodeError
    from app.skills import queue_bus

    _MAX_FIX_PASSES = 2

    async with SessionLocal() as db:
        row = (
            await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
        ).scalar_one_or_none()
        if row is None:
            return
        payload = row.payload or {}
        doc_id = payload.get("generated_document_id")
        prompt = payload.get("prompt")
        source_doc_id = payload.get("source_doc_id")
        source_title = payload.get("source_title") or ""
        source_body = payload.get("source_body") or ""
        plant_mistakes = bool(payload.get("plant_mistakes", True))
        if not doc_id or not prompt:
            await _fail(db, row, "humanize task missing doc_id or prompt")
            return

        label = row.label or f"Humanize: {source_title}"

        # First pass. Rate limits park the queue row; other errors mark the doc.
        try:
            final_text = await queue_bus.run_claude_to_bus(
                prompt=prompt,
                source="humanize",
                item_id=f"queue:{row.id}",
                label=label,
                allowed_tools=[],
                timeout_seconds=600,
                action="humanize",
            )
        except ClaudeCodeError as exc:
            err = str(exc)
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err)
            await _mark_doc(
                doc_id,
                structured={
                    "status": "error",
                    "finished_at": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
                    "error": f"Claude Code error: {exc}",
                },
            )
            return
        except Exception as exc:  # pragma: no cover
            await _fail(db, row, f"Unexpected error: {exc}")
            log.exception("Humanize task %d unhandled error", row.id)
            return

        from app.api.v1.documents import (
            _extract_json_object,
            _validate_humanizer_output,
            _HUMANIZE_FIX_PROMPT,
            _FIX_PRESERVE_IMPERFECTIONS,
            _FIX_NO_IMPERFECTIONS,
        )

        data = _extract_json_object(final_text) or {}
        content_md = (data.get("content_md") or "").strip()
        if not content_md:
            # Exit-0 usage-cap message path — park for cooldown instead of
            # erroring the doc (see _handle_tailor).
            if _is_rate_limited(final_text):
                await _handle_rate_limit(db, row, final_text)
                return
            await _fail(db, row, "Humanizer returned no content.")
            await _mark_doc(
                doc_id,
                structured={
                    "status": "error",
                    "finished_at": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
                    "error": "Humanizer returned no content.",
                },
            )
            return

        fix_notes: list[str] = []
        for pass_idx in range(_MAX_FIX_PASSES):
            violations = _validate_humanizer_output(content_md, source_body=source_body)
            if not violations:
                break
            log.info(
                "Humanize task %d fix-pass %d: %d violations",
                row.id, pass_idx + 1, len(violations),
            )
            violations_block = "\n".join(f"- {v}" for v in violations)
            fix_prompt = _HUMANIZE_FIX_PROMPT.format(
                violations=violations_block,
                previous_output=content_md.replace("{", "{{").replace("}", "}}"),
                source_body=source_body.replace("{", "{{").replace("}", "}}"),
                imperfections_directive=(
                    _FIX_PRESERVE_IMPERFECTIONS
                    if plant_mistakes
                    else _FIX_NO_IMPERFECTIONS
                ),
            )
            try:
                fix_text = await queue_bus.run_claude_to_bus(
                    prompt=fix_prompt,
                    source="humanize",
                    item_id=f"queue:{row.id}",
                    label=f"Humanize fix-pass {pass_idx + 1}: {source_title}",
                    allowed_tools=[],
                    timeout_seconds=600,
                    action="humanize",
                )
            except ClaudeCodeError as exc:
                err = str(exc)
                if _is_rate_limited(err):
                    # Park for cooldown but keep what we've got so far — next
                    # run starts from the main pass again, which is fine.
                    await _handle_rate_limit(db, row, err)
                    return
                log.warning("Humanize fix-pass %d failed: %s — keeping prior", pass_idx + 1, exc)
                break
            fix_data = _extract_json_object(fix_text) or {}
            new_md = (fix_data.get("content_md") or "").strip()
            if not new_md:
                break
            content_md = new_md
            data = fix_data
            fix_notes.append(
                f"Pass {pass_idx + 1} fixed: {', '.join(violations[:4])}"
                + ("…" if len(violations) > 4 else "")
            )

        residual_violations = _validate_humanizer_output(content_md, source_body=source_body)

        claude_warning = data.get("warning")
        warning_parts: list[str] = []
        if claude_warning:
            warning_parts.append(str(claude_warning))
        if residual_violations:
            warning_parts.append(
                "After retries, these AI-tell patterns still slipped through — "
                "consider a manual pass:\n  - " + "\n  - ".join(residual_violations)
            )
        final_warning = "\n\n".join(warning_parts) if warning_parts else None

        claude_notes = data.get("notes")
        notes_parts: list[str] = []
        if claude_notes:
            notes_parts.append(str(claude_notes))
        if fix_notes:
            notes_parts.append("Fix-pass summary: " + " | ".join(fix_notes))
        final_notes = " · ".join(notes_parts) if notes_parts else None

        raw_mistakes = data.get("intentional_mistakes") or []
        intentional_mistakes: list[dict] = []
        if isinstance(raw_mistakes, list):
            for m in raw_mistakes:
                if not isinstance(m, dict):
                    continue
                desc = str(m.get("description") or "").strip()
                excerpt = str(m.get("excerpt") or "").strip()
                if not desc:
                    continue
                intentional_mistakes.append(
                    {"description": desc[:240], "excerpt": excerpt[:240]}
                )

        await _mark_doc(
            doc_id,
            content_md=content_md,
            structured={
                "status": "ready",
                "finished_at": _dt.now(tz=_tz.utc).isoformat(timespec="seconds"),
                "humanized_source_doc_id": source_doc_id,
                "notes": final_notes,
                "warning": final_warning,
                "error": None,
                "humanize_fix_passes": len(fix_notes),
                "humanize_residual_violations": residual_violations or None,
                "intentional_mistakes": intentional_mistakes or None,
            },
        )

        row.state = "done"
        row.result = {"generated_document_id": doc_id}
        row.error_message = None
        if isinstance(row.payload, dict) and "rate_limit_count" in row.payload:
            new_payload = dict(row.payload)
            new_payload.pop("rate_limit_count", None)
            row.payload = new_payload or None
        await db.commit()
        log.info("Humanize task %d → updated GeneratedDocument %d", row.id, doc_id)


async def _handle_org_research(item: JobFetchQueue) -> None:
    """Run the company-research pipeline against an organization_id
    in the queue row's payload. Re-uses the same direct-fetch +
    parse pipeline the HTTP endpoint uses (no Claude exploration —
    one or two httpx GETs followed by a single no-tool parse)."""
    from app.api.v1.organizations import run_org_research_pipeline
    from app.models.jobs import Organization
    from app.skills.runner import ClaudeCodeError

    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(JobFetchQueue).where(JobFetchQueue.id == item.id)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        payload = row.payload or {}
        org_id = payload.get("organization_id")
        if not org_id:
            await _fail(db, row, "org_research task missing organization_id")
            return

        org = (
            await db.execute(
                select(Organization).where(
                    Organization.id == org_id,
                    Organization.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if org is None:
            await _fail(db, row, f"Organization {org_id} not found")
            return

        try:
            await run_org_research_pipeline(db, org)
        except ClaudeCodeError as exc:
            err = str(exc)
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err)
            return
        except Exception as exc:  # pragma: no cover
            await _fail(db, row, f"Unexpected error: {exc}")
            log.exception("org_research task %d unhandled error", row.id)
            return

        # Re-load the queue row — run_org_research_pipeline commits
        # internally so the existing reference is detached.
        row = (
            await db.execute(
                select(JobFetchQueue).where(JobFetchQueue.id == item.id)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.state = "done"
        row.result = {"organization_id": org_id}
        row.error_message = None
        if isinstance(row.payload, dict) and "rate_limit_count" in row.payload:
            new_payload = dict(row.payload)
            new_payload.pop("rate_limit_count", None)
            row.payload = new_payload or None
        await db.commit()
        log.info("org_research task %d → enriched Organization %d", row.id, org_id)


async def _handle_prep(item: JobFetchQueue) -> None:
    """Generate resume_emphasis / cover_letter_hook / interview_focus_areas
    for a TrackedJob the user has flipped to `interested`. Merges the
    result into job.jd_analysis so the slim triage card and the prep
    hints share one storage location.

    Like `_handle_score`, this is one-shot — bad inputs fail
    permanently rather than burning 3 retries to reach the same
    outcome. Rate-limit cooldowns still retry via _handle_rate_limit."""
    from app.skills.runner import ClaudeCodeError
    from app.skills import queue_bus

    async with SessionLocal() as db:
        row = (
            await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
        ).scalar_one_or_none()
        if row is None:
            return
        payload = row.payload or {}
        tracked_job_id = payload.get("tracked_job_id")
        if not tracked_job_id:
            await _fail(db, row, "prep task missing tracked_job_id", permanent=True)
            return

        job = (
            await db.execute(
                select(TrackedJob).where(
                    TrackedJob.id == tracked_job_id,
                    TrackedJob.user_id == row.user_id,
                    TrackedJob.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if job is None:
            await _fail(
                db, row,
                f"TrackedJob {tracked_job_id} not found",
                permanent=True,
            )
            return
        if not (job.job_description and job.job_description.strip()):
            await _fail(db, row, "job has no description to prep against", permanent=True)
            return

        from app.api.v1.jobs import _build_jd_prep_prompt, _extract_json_object
        from app.core.security import create_access_token

        org_name: Optional[str] = None
        if job.organization_id:
            from app.models.jobs import Organization as _Org
            org_row = (
                await db.execute(
                    select(_Org.name).where(_Org.id == job.organization_id)
                )
            ).first()
            org_name = org_row[0] if org_row else None

        prompt = _build_jd_prep_prompt(job, org_name)
        api_token = create_access_token(
            subject=str(row.user_id), extra={"purpose": "jd_prep"}
        )

        label = row.label or f"Prep: {job.title}"
        try:
            final_text = await queue_bus.run_claude_to_bus(
                prompt=prompt,
                source="jd_prep",
                item_id=f"queue:{row.id}",
                label=label,
                allowed_tools=["Bash"],
                extra_env={
                    "JSP_API_BASE_URL": "http://localhost:8000",
                    "JSP_API_TOKEN": api_token,
                },
                timeout_seconds=240,
                action="interview_prep",
            )
        except ClaudeCodeError as exc:
            err = str(exc)
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err, permanent=True)
            return
        except Exception as exc:  # pragma: no cover
            await _fail(db, row, f"Unexpected error: {exc}", permanent=True)
            log.exception("Prep task %d unhandled error", row.id)
            return

        data = _extract_json_object(final_text) or {}
        if not data:
            # Exit-0 usage-cap message path — park for cooldown instead of a
            # permanent failure (see _handle_score).
            if _is_rate_limited(final_text):
                await _handle_rate_limit(db, row, final_text)
                return
            snippet = (final_text or "").strip()
            if len(snippet) > 600:
                snippet = snippet[:300] + " […] " + snippet[-300:]
            await _fail(
                db, row,
                "Prep analyzer returned no parseable JSON. "
                f"Raw Claude output (truncated): {snippet!r}",
                permanent=True,
            )
            return

        # Merge into job.jd_analysis so the slim triage card (paragraph
        # / pros / cons) and these prep hints share one column.
        prior = job.jd_analysis if isinstance(job.jd_analysis, dict) else {}
        merged = dict(prior)
        for key in ("resume_emphasis", "cover_letter_hook", "interview_focus_areas"):
            if key in data:
                merged[key] = data[key]
        job.jd_analysis = merged

        row.state = "done"
        row.result = {"tracked_job_id": job.id, "merged_keys": list(data.keys())}
        row.error_message = None
        if isinstance(row.payload, dict) and "rate_limit_count" in row.payload:
            new_payload = dict(row.payload)
            new_payload.pop("rate_limit_count", None)
            row.payload = new_payload or None
        await db.commit()
        log.info(
            "Prep task %d → merged %s into TrackedJob %d",
            row.id, list(data.keys()), job.id,
        )


# kind → handler. Extensible: add new kinds here.
_HANDLERS = {
    "fetch": _handle_fetch,
    "score": _handle_score,
    "tailor": _handle_tailor,
    "humanize": _handle_humanize,
    "org_research": _handle_org_research,
    "prep": _handle_prep,
}


async def _process(item: JobFetchQueue) -> None:
    """Dispatch a claimed queue row to its kind-specific handler."""
    kind = item.kind or "fetch"
    handler = _HANDLERS.get(kind)
    if handler is None:
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(JobFetchQueue).where(JobFetchQueue.id == item.id)
                )
            ).scalar_one_or_none()
            if row is not None:
                await _fail(db, row, f"Unknown task kind '{kind}' — no handler registered")
        return
    await handler(item)


async def run_forever() -> None:
    """Main loop. Resets stuck rows once on boot, then polls indefinitely.

    Concurrency: claims happen sequentially from this single loop so the
    SELECT-then-UPDATE in `_claim_next` can't race with itself. Each
    claimed row dispatches to its own asyncio task; we keep up to
    `worker_settings.get_max_parallel()` in flight at once. The limit is
    re-read on every iteration so the user can change it on /queue
    without restarting the API.
    """
    from app.skills import worker_settings as _ws

    try:
        await _reset_stuck_rows()
    except Exception:  # pragma: no cover
        log.exception("Queue worker: stuck-row reset failed on boot")

    import time as _time

    _ensure_claude_cleanup_setting()
    try:
        await _prune_old_rows()
        removed, freed = await asyncio.to_thread(_prune_claude_byproducts_sync)
        if removed:
            log.info(
                "Pruned %d Claude byproduct file(s), freed %.1f MB",
                removed, freed / 1_048_576,
            )
    except Exception:  # pragma: no cover
        log.exception("Queue worker: prune failed on boot")
    last_prune = _time.monotonic()

    running: set[asyncio.Task] = set()

    async def _supervised_process(item: JobFetchQueue) -> None:
        try:
            await _process(item)
        except Exception:  # pragma: no cover
            log.exception("Queue worker: _process raised unexpectedly")

    while True:
        # Daily prune of long-finished rows + Claude CLI byproducts.
        # Cheap check per iteration.
        if _time.monotonic() - last_prune >= PRUNE_INTERVAL_SECONDS:
            last_prune = _time.monotonic()
            try:
                await _prune_old_rows()
                removed, freed = await asyncio.to_thread(
                    _prune_claude_byproducts_sync
                )
                if removed:
                    log.info(
                        "Pruned %d Claude byproduct file(s), freed %.1f MB",
                        removed, freed / 1_048_576,
                    )
            except Exception:  # pragma: no cover
                log.exception("Queue worker: periodic prune failed")

        # Wait for an open slot if we're at capacity. Re-read the limit
        # every cycle so changes from the UI apply immediately.
        if len(running) >= _ws.get_max_parallel():
            # Block on whichever task finishes first — no busy poll.
            done, _pending = await asyncio.wait(
                running, return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                running.discard(t)
            continue

        try:
            async with SessionLocal() as db:
                item = await _claim_next(db)
        except Exception:  # pragma: no cover
            log.exception("Queue worker: claim error")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        if item is None:
            # Nothing to claim. Wait either for the poll interval OR for
            # an in-flight task to finish (it might enqueue follow-ups).
            if running:
                done, _pending = await asyncio.wait(
                    running,
                    timeout=POLL_INTERVAL_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in done:
                    running.discard(t)
            else:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        task = asyncio.create_task(
            _supervised_process(item), name=f"qworker-{item.id}"
        )
        running.add(task)
        task.add_done_callback(running.discard)
        # Tight loop: try to claim another immediately. Falls back to
        # the capacity wait above on the next iteration if we're full.
