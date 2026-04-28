"""Source-poller background worker.

Tick loop: every PoLL_TICK_SECONDS, scan all enabled JobSource rows
whose `last_polled_at` is older than `poll_interval_hours` and pull
fresh leads from the matching adapter. Leads are deduped on
`(source_id, external_id)`, filtered by per-source filters, and
rejected if they expired before they were even surfaced (rare, but
upstream `posted_at` can be ancient on first poll).

The worker also expires leads: any `state=new` row whose `expires_at`
has passed gets flipped to `state=expired` so the UI can hide it.

Single-tenant deployment, so there's exactly one poller per process.
Coordination across replicas would need a real lock; not in scope."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.sources import JobLead, JobSource
from app.sources import ADAPTERS

log = logging.getLogger(__name__)

# Wake every minute. Per-source schedule is enforced inside the tick.
POLL_TICK_SECONDS = 60


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _matches_filters(lead: dict[str, Any], filters: Optional[dict]) -> bool:
    """Apply user-defined per-source filters. None = pass.

    Filter shape (all optional):
      {
        "title_include": "react|frontend",  # regex, must match
        "title_exclude": "principal|staff", # regex, must NOT match
        "location_include": "remote|new york",
        "location_exclude": "germany",
        "remote_only": true,
      }
    """
    if not filters:
        return True
    title = (lead.get("title") or "").lower()
    location = (lead.get("location") or "").lower()
    remote = (lead.get("remote_policy") or "").lower()
    try:
        inc_t = filters.get("title_include")
        if inc_t and not re.search(inc_t, title, re.IGNORECASE):
            return False
        exc_t = filters.get("title_exclude")
        if exc_t and re.search(exc_t, title, re.IGNORECASE):
            return False
        inc_l = filters.get("location_include")
        if inc_l and not re.search(inc_l, location, re.IGNORECASE):
            return False
        exc_l = filters.get("location_exclude")
        if exc_l and re.search(exc_l, location, re.IGNORECASE):
            return False
        if filters.get("remote_only") and remote != "remote":
            return False
    except re.error:
        # A malformed user regex shouldn't break the whole poll — log and
        # treat the filter as a no-op for that field.
        log.warning("source filter regex invalid: %r", filters)
    return True


async def _adapter_fetch(kind: str, slug_or_url: str) -> list[dict[str, Any]]:
    fn = ADAPTERS.get(kind)
    if fn is None:
        raise ValueError(f"Unknown source kind: {kind!r}")
    return await fn(slug_or_url)


async def poll_source(db: AsyncSession, source: JobSource) -> tuple[int, Optional[str]]:
    """Fetch + persist new leads for a single source. Returns
    (new_lead_count, error_message). Caller commits."""
    try:
        raw_leads = await _adapter_fetch(source.kind, source.slug_or_url)
    except Exception as exc:  # noqa: BLE001
        # Format a more actionable message for the most common failure
        # mode (HTTP 404 — wrong slug or company isn't on this ATS).
        msg = str(exc)
        try:
            import httpx  # local import keeps adapters loosely coupled

            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                code = exc.response.status_code
                if code == 404:
                    msg = (
                        f"{source.kind} returned 404 for slug "
                        f"'{source.slug_or_url}'. Either the slug is wrong "
                        f"or that company isn't on {source.kind}."
                    )
                elif code in (401, 403):
                    msg = (
                        f"{source.kind} returned {code} for slug "
                        f"'{source.slug_or_url}' — feed appears private."
                    )
                elif code == 429:
                    msg = (
                        f"{source.kind} rate-limited us. Increase the "
                        "poll interval and try again later."
                    )
        except Exception:
            pass
        log.warning(
            "source %s/%s fetch failed: %s",
            source.kind,
            source.slug_or_url,
            msg,
        )
        source.last_polled_at = _now()
        source.last_error = msg[:1000]
        return 0, msg

    now = _now()
    expires = now + timedelta(hours=max(1, source.lead_ttl_hours))
    inserted = 0
    for raw in raw_leads:
        if not _matches_filters(raw, source.filters):
            continue
        ext_id = (raw.get("external_id") or "").strip()
        title = (raw.get("title") or "").strip()
        if not ext_id or not title:
            continue
        lead = JobLead(
            user_id=source.user_id,
            source_id=source.id,
            external_id=ext_id[:255],
            title=title[:500],
            organization_name=(raw.get("organization_name") or None),
            location=(raw.get("location") or None),
            remote_policy=(raw.get("remote_policy") or None),
            source_url=(raw.get("source_url") or None),
            description_md=raw.get("description_md") or None,
            posted_at=raw.get("posted_at"),
            first_seen_at=now,
            expires_at=expires,
            state="new",
            raw_payload=raw.get("raw"),
        )
        db.add(lead)
        try:
            # Flush so the unique-constraint violation surfaces NOW, per
            # row, instead of poisoning the whole transaction.
            await db.flush()
            inserted += 1
        except IntegrityError:
            # Duplicate — already saw this posting on a previous poll.
            await db.rollback()
            # We need to re-attach `source` because rollback expires it.
            source = await db.get(JobSource, source.id)
            if source is None:
                return inserted, None

    source.last_polled_at = now
    source.last_lead_count = inserted
    source.last_error = None
    return inserted, None


async def _expire_old_leads(db: AsyncSession) -> int:
    """Flip `state=new` leads whose `expires_at` has passed to `expired`."""
    now = _now()
    result = await db.execute(
        update(JobLead)
        .where(JobLead.state == "new", JobLead.expires_at < now)
        .values(state="expired")
    )
    return result.rowcount or 0


async def _due_sources(db: AsyncSession) -> list[JobSource]:
    """Sources that should be polled this tick: enabled, not soft-deleted,
    and either never polled or polled longer ago than their interval."""
    now = _now()
    rows = (
        await db.execute(
            select(JobSource).where(
                JobSource.enabled.is_(True),
                JobSource.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    due: list[JobSource] = []
    for s in rows:
        if s.last_polled_at is None:
            due.append(s)
            continue
        cutoff = now - timedelta(hours=max(1, s.poll_interval_hours))
        if s.last_polled_at < cutoff:
            due.append(s)
    return due


async def _tick() -> None:
    async with SessionLocal() as db:
        try:
            expired = await _expire_old_leads(db)
            if expired:
                log.info("Expired %d stale leads", expired)
            due = await _due_sources(db)
            for source in due:
                count, err = await poll_source(db, source)
                if err is not None:
                    log.info(
                        "source %s/%s poll error: %s",
                        source.kind,
                        source.slug_or_url,
                        err,
                    )
                else:
                    log.info(
                        "source %s/%s polled — %d new leads",
                        source.kind,
                        source.slug_or_url,
                        count,
                    )
            await db.commit()
        except Exception:
            log.exception("Source poll tick failed")
            await db.rollback()


async def run_forever() -> None:
    """Long-running worker. Started in app.main lifespan."""
    log.info("Source poller starting (tick=%ds)", POLL_TICK_SECONDS)
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("Source poller tick crashed; continuing")
        await asyncio.sleep(POLL_TICK_SECONDS)


__all__ = ["run_forever", "poll_source"]
