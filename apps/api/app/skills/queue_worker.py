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
from datetime import datetime, time as _dt_time, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.jobs import JobFetchQueue, TrackedJob

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
STUCK_RESET_MINUTES = 20
MAX_ATTEMPTS = 3

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


async def _fail(db: AsyncSession, row: JobFetchQueue, err: str) -> None:
    """Mark a row errored (permanent if attempts exhausted, else re-queue)."""
    row.state = "error" if row.attempts >= MAX_ATTEMPTS else "queued"
    row.error_message = err
    await db.commit()
    log.warning(
        "Queue item %d (%s) failed (attempt %d): %s",
        row.id, row.kind or "fetch", row.attempts, err,
    )


async def _handle_fetch(item: JobFetchQueue) -> None:
    """Claim-a-URL → fetch → create TrackedJob."""
    from app.api.v1.jobs import build_tracked_job_payload, perform_fetch
    from app.skills.runner import ClaudeCodeError
    from app.skills import queue_bus

    async with SessionLocal() as db:
        row = (
            await db.execute(select(JobFetchQueue).where(JobFetchQueue.id == item.id))
        ).scalar_one_or_none()
        if row is None:
            return
        item_id = row.id
        item_url = row.url
        label = row.label or row.url or f"Fetch #{row.id}"

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

        try:
            fetched = await perform_fetch(db, row.url, on_event=_on_event)
        except ClaudeCodeError as exc:
            err = str(exc)
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err)
            return
        except Exception as exc:  # pragma: no cover
            await _fail(db, row, f"Unexpected error: {exc}")
            log.exception("Fetch task %d unhandled error", row.id)
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

        job = TrackedJob(user_id=row.user_id, **payload)
        db.add(job)
        await db.flush()

        from app.models.jobs import ApplicationEvent
        db.add(ApplicationEvent(
            tracked_job_id=job.id,
            event_type="note",
            event_date=datetime.now(tz=timezone.utc),
            details_md=f"Created from fetch-queue URL `{row.url}`.",
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
            await _fail(db, row, "score task missing tracked_job_id")
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
            await _fail(db, row, f"TrackedJob {tracked_job_id} not found")
            return
        if not (job.job_description and job.job_description.strip()):
            await _fail(db, row, "job has no description to analyze")
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
            )
        except ClaudeCodeError as exc:
            err = str(exc)
            if _is_rate_limited(err):
                await _handle_rate_limit(db, row, err)
                return
            await _fail(db, row, err)
            return
        except Exception as exc:  # pragma: no cover
            await _fail(db, row, f"Unexpected error: {exc}")
            log.exception("Score task %d unhandled error", row.id)
            return

        data = _extract_json_object(final_text) or {}
        if not data:
            await _fail(db, row, "JD analyzer returned no parseable JSON")
            return
        _apply_jd_analysis_to_job(job, data)
        row.state = "done"
        row.result = {"tracked_job_id": job.id, "fit_score": data.get("score")}
        row.error_message = None
        if isinstance(row.payload, dict) and "rate_limit_count" in row.payload:
            new_payload = dict(row.payload)
            new_payload.pop("rate_limit_count", None)
            row.payload = new_payload or None
        await db.commit()
        log.info("Score task %d → applied jd_analysis to TrackedJob %d", row.id, job.id)


# kind → handler. Extensible: add new kinds here.
_HANDLERS = {
    "fetch": _handle_fetch,
    "score": _handle_score,
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
    """Main loop. Resets stuck rows once on boot, then polls indefinitely."""
    try:
        await _reset_stuck_rows()
    except Exception:  # pragma: no cover
        log.exception("Queue worker: stuck-row reset failed on boot")

    while True:
        try:
            async with SessionLocal() as db:
                item = await _claim_next(db)
        except Exception:  # pragma: no cover
            log.exception("Queue worker: claim error")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        if item is None:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue

        try:
            await _process(item)
        except Exception:  # pragma: no cover
            log.exception("Queue worker: _process raised unexpectedly")
        # Immediately try for another item — if there's more queued work
        # the user is probably waiting, and each fetch takes 60–180s.
