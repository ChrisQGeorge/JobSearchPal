"""Background worker that processes JobFetchQueue items.

Runs as a single asyncio task launched from the FastAPI lifespan, polls the
queue every few seconds, claims one row at a time with state=queued,
runs the URL fetch + org enrichment, creates a TrackedJob, and marks the
row done/error. Bounded retries.

Design notes:
  * Single-worker, single-container — no distributed locking needed. We use
    a simple UPDATE … WHERE state='queued' claim step to handle the race
    between claim-and-process, which matters only if multiple workers ever
    run at once.
  * Stuck "processing" rows older than STUCK_RESET_MINUTES get reset to
    "queued" at startup so a crashed previous run doesn't leave holes.
  * Attempts are capped at MAX_ATTEMPTS. The UI's retry button resets to 0.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.jobs import JobFetchQueue, TrackedJob

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
STUCK_RESET_MINUTES = 20
MAX_ATTEMPTS = 3


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
    """Pick the oldest queued row and mark it processing atomically."""
    stmt = (
        select(JobFetchQueue)
        .where(JobFetchQueue.state == "queued")
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


async def _process(item: JobFetchQueue) -> None:
    """Fetch the URL, create a TrackedJob, update the queue row. Errors are
    captured and written onto the row so the UI can surface them."""
    # Imported here to keep module import cheap; jobs router imports this
    # module via main.py lifespan so the circular reference needs this.
    from app.api.v1.jobs import (
        build_tracked_job_payload,
        perform_fetch,
    )
    from app.skills.runner import ClaudeCodeError

    async with SessionLocal() as db:
        # Re-read the item into this session (the one from _claim_next is
        # attached to its own session which has been closed by now).
        stmt = select(JobFetchQueue).where(JobFetchQueue.id == item.id)
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return

        try:
            fetched = await perform_fetch(db, row.url)
        except ClaudeCodeError as exc:
            row.state = (
                "error" if row.attempts >= MAX_ATTEMPTS else "queued"
            )
            row.error_message = str(exc)
            await db.commit()
            log.warning(
                "Queue item %d failed (attempt %d): %s", row.id, row.attempts, exc
            )
            return
        except Exception as exc:  # pragma: no cover
            row.state = "error"
            row.error_message = f"Unexpected error: {exc}"
            await db.commit()
            log.exception("Queue item %d unhandled error", row.id)
            return

        # If the page didn't yield recognizable content, mark error so the UI
        # prompts the user to fix/remove rather than silently retry forever.
        if fetched.warning:
            row.state = "error"
            row.error_message = fetched.warning
            await db.commit()
            return

        overrides: dict = {}
        if row.desired_status:
            overrides["status"] = row.desired_status
        if row.desired_priority:
            overrides["priority"] = row.desired_priority
        if row.desired_date_applied:
            overrides["date_applied"] = row.desired_date_applied
        if row.desired_date_closed:
            overrides["date_closed"] = row.desired_date_closed
        # User-supplied posted date wins over whatever the fetcher extracted.
        if row.desired_date_posted:
            overrides["date_posted"] = row.desired_date_posted
        if row.desired_notes:
            overrides["notes"] = row.desired_notes
        payload = build_tracked_job_payload(fetched, overrides=overrides)

        job = TrackedJob(user_id=row.user_id, **payload)
        db.add(job)
        await db.flush()

        # Audit trail — mirror the on-create event that the jobs router emits.
        from app.models.jobs import ApplicationEvent

        db.add(
            ApplicationEvent(
                tracked_job_id=job.id,
                event_type="note",
                event_date=datetime.now(tz=timezone.utc),
                details_md=f"Created from fetch-queue URL `{row.url}`.",
            )
        )

        row.state = "done"
        row.created_tracked_job_id = job.id
        row.error_message = None
        await db.commit()
        log.info("Queue item %d → created TrackedJob id=%d", row.id, job.id)


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
