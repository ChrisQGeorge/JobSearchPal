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
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import BgSessionLocal as SessionLocal  # background pool
from app.models.sources import JobLead, JobSource
from app.sources import ADAPTERS

log = logging.getLogger(__name__)

# Wake every minute. Per-source schedule is enforced inside the tick.
POLL_TICK_SECONDS = 60
# Large Bright Data discovery runs can take tens of minutes; past this a
# parked snapshot is abandoned with an error instead of polled forever.
PENDING_GIVE_UP = timedelta(hours=3)


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


async def _adapter_fetch(
    kind: str,
    slug_or_url: str,
    ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    fn = ADAPTERS.get(kind)
    if fn is None:
        raise ValueError(f"Unknown source kind: {kind!r}")
    return await fn(slug_or_url, ctx)


async def _build_ctx(
    db: AsyncSession, source: JobSource
) -> dict[str, Any]:
    """Per-kind context dict — credentials for paid sources, filter
    pass-through for everything. Adapters that don't need any of this
    just ignore it."""
    ctx: dict[str, Any] = {
        "filters": source.filters,
        "max_leads_per_poll": max(1, int(source.max_leads_per_poll or 100)),
    }
    if source.kind in (
        "brightdata_linkedin", "brightdata_glassdoor", "brightdata_keyword"
    ):
        from app.api.v1.api_credentials import get_user_secret

        ctx["api_key"] = await get_user_secret(
            db, source.user_id, "brightdata", "default"
        )
        # Allow a per-source dataset_id override via filters.
        if isinstance(source.filters, dict):
            ds = source.filters.get("dataset_id")
            if isinstance(ds, str) and ds.strip():
                ctx["dataset_id"] = ds.strip()
    return ctx


async def poll_source(
    db: AsyncSession, source: JobSource, *, quick: bool = False
) -> tuple[int, Optional[str]]:
    """Fetch + persist new leads for a single source. Returns
    (new_lead_count, error_message). Caller commits.

    `quick=True` (foreground "Poll now" requests) caps the Bright Data
    snapshot wait at ~20s so the HTTP request returns before any proxy
    timeout: a slow run parks as pending and this background worker
    finishes collecting it within the next tick."""
    from app.sources.brightdata import SnapshotPending

    if source.kind == "brightdata_keyword":
        return await _poll_keyword(db, source, quick=quick)

    try:
        ctx = await _build_ctx(db, source)
        if quick:
            ctx["snapshot_wait_seconds"] = 20
        raw_leads = await _adapter_fetch(source.kind, source.slug_or_url, ctx)
    except SnapshotPending as sp:
        # The paid run was triggered but isn't done collecting. Park the
        # snapshot_id on the source so the next attempt RESUMES it
        # instead of triggering (and paying for) a fresh run.
        # last_polled_at is deliberately NOT bumped — the source stays
        # "due", so the next poller tick (60s) picks collection back up.
        f = dict(source.filters or {})
        if f.get("pending_snapshot_id") != sp.snapshot_id:
            f["pending_since"] = _now().isoformat(timespec="seconds")
        f["pending_snapshot_id"] = sp.snapshot_id
        try:
            started = datetime.fromisoformat(f["pending_since"])
        except (KeyError, ValueError):
            started = _now()
        if _now() - started > PENDING_GIVE_UP:
            f.pop("pending_snapshot_id", None)
            f.pop("pending_since", None)
            source.filters = f
            source.last_polled_at = _now()
            msg = (
                f"Bright Data snapshot {sp.snapshot_id} still wasn't ready after "
                f"{int(PENDING_GIVE_UP.total_seconds() // 3600)}h — gave up. Check "
                "the run in the Bright Data dashboard, or try a smaller query."
            )
            source.last_error = msg
            return 0, msg
        source.filters = f
        # Not an error — the UI shows a "collecting" spinner off
        # pending_snapshot_id instead.
        source.last_error = None
        log.info(
            "source %s/%s snapshot pending: %s",
            source.kind, source.slug_or_url, sp.snapshot_id,
        )
        return 0, None
    except Exception as exc:  # noqa: BLE001
        # A parked snapshot that errors out (dead snapshot, auth change)
        # must not wedge the source forever — drop it so the next
        # scheduled poll triggers a fresh run.
        if isinstance(source.filters, dict) and source.filters.get(
            "pending_snapshot_id"
        ):
            f = dict(source.filters)
            f.pop("pending_snapshot_id", None)
            f.pop("pending_since", None)
            source.filters = f
        # Format a more actionable message for the most common failure
        # modes — httpx 4xx, transport errors, bot-gate interstitials.
        msg = str(exc)
        try:
            import httpx  # local import keeps adapters loosely coupled

            from app.sources._common import UpstreamGateError

            if isinstance(exc, UpstreamGateError):
                # Already actionable as-is; just keep it short for the
                # source row's last_error field.
                msg = str(exc)
            elif isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
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
                elif 500 <= code < 600:
                    msg = (
                        f"{source.kind} returned {code} (server error). "
                        "The next scheduled poll will retry automatically."
                    )
            elif isinstance(exc, httpx.TimeoutException):
                msg = (
                    f"{source.kind} request timed out — the upstream is "
                    "slow or unreachable. The next scheduled poll will "
                    "retry automatically."
                )
            elif isinstance(exc, httpx.ConnectError):
                msg = (
                    f"{source.kind} connection failed — DNS, TLS, or "
                    "network blocked. Check the URL is correct."
                )
        except Exception:
            pass
        log.warning(
            "source %s/%s fetch failed: %s",
            source.kind,
            source.slug_or_url,
            msg,
        )
        # Append a JSONL line to /app/logs/source_errors.jsonl so the
        # Companion (and any external tail-able log scrape) can
        # diagnose failures without round-tripping through the API.
        try:
            from app.sources._errlog import log_source_error

            log_source_error(
                user_id=source.user_id,
                source_id=source.id,
                kind=source.kind,
                slug_or_url=source.slug_or_url,
                error_class=type(exc).__name__,
                error_message=str(exc),
            )
        except Exception:
            # Diagnostics must never break the poller.
            pass
        source.last_polled_at = _now()
        source.last_error = msg[:1000]
        return 0, msg

    # Successful fetch — clear any parked snapshot (it was collected).
    if isinstance(source.filters, dict) and source.filters.get(
        "pending_snapshot_id"
    ):
        f = dict(source.filters)
        f.pop("pending_snapshot_id", None)
        f.pop("pending_since", None)
        source.filters = f

    cap = max(1, int(source.max_leads_per_poll or 100))
    inserted, err, auto_dismissed = await _insert_leads(db, source, raw_leads, cap)
    if err is not None:
        return 0, err
    source.last_polled_at = _now()
    source.last_lead_count = inserted
    source.last_error = None
    _set_filters(source, last_auto_dismissed=auto_dismissed or None)
    return inserted, None


async def _insert_leads(
    db: AsyncSession, source: JobSource, raw_leads: list[dict[str, Any]], cap: int
) -> tuple[int, Optional[str], int]:
    """Dedupe + filter + insert up to `cap` new JobLead rows. Returns
    (inserted, error, auto_dismissed) — error only on a concurrent-insert
    race. Leads matching one of the user's auto-dismiss keyword filters
    are stored already dismissed (so dedupe keeps them from coming back)
    and don't count toward `cap`."""
    from app.skills.lead_filters import auto_dismiss_filters, compile_matcher

    try:
        # Compiled once per batch; each lead is then a few regex checks.
        auto_filters = [compile_matcher(f) for f in auto_dismiss_filters(source.user_id)]
    except Exception:  # pragma: no cover — a bad store must not block imports
        log.exception("Could not load auto-dismiss filters")
        auto_filters = []
    auto_dismissed = 0
    now = _now()
    expires = now + timedelta(hours=max(1, source.lead_ttl_hours))

    # Pre-fetch every external_id we already have for this source. Used to
    # dedupe in-Python so we never hit the unique constraint and have to
    # roll back mid-poll. Earlier versions caught IntegrityError per
    # insert and tried to recover by rolling back the session, which left
    # the async pool in a bad state and exploded with MissingGreenlet on
    # the next access.
    existing_ext = set(
        (
            await db.execute(
                select(JobLead.external_id).where(
                    JobLead.source_id == source.id,
                )
            )
        ).scalars().all()
    )

    inserted = 0
    for raw in raw_leads:
        if inserted >= cap:
            # Hit the per-poll cap. Remaining raws stay on upstream;
            # next poll will pick up whatever's still un-dedup'd.
            break
        if not _matches_filters(raw, source.filters):
            continue
        ext_id = (raw.get("external_id") or "").strip()
        title = (raw.get("title") or "").strip()
        if not ext_id or not title:
            continue
        ext_id = ext_id[:255]
        if ext_id in existing_ext:
            continue
        existing_ext.add(ext_id)
        dismiss = bool(auto_filters) and any(
            m({**raw, "title": title}) for m in auto_filters
        )
        db.add(
            JobLead(
                user_id=source.user_id,
                source_id=source.id,
                external_id=ext_id,
                title=title[:500],
                organization_name=(raw.get("organization_name") or None),
                location=(raw.get("location") or None),
                remote_policy=(raw.get("remote_policy") or None),
                source_url=(raw.get("source_url") or None),
                description_md=raw.get("description_md") or None,
                posted_at=raw.get("posted_at"),
                first_seen_at=now,
                expires_at=expires,
                state="dismissed" if dismiss else "new",
                raw_payload=raw.get("raw"),
            )
        )
        if dismiss:
            auto_dismissed += 1
        else:
            inserted += 1

    # Flush once so any unrelated FK / type errors surface here while we
    # still have a clean session (and the caller's commit can proceed).
    if inserted or auto_dismissed:
        try:
            await db.flush()
        except IntegrityError as exc:
            # Two concurrent polls can race — pre-fetch said "no row"
            # but the other tick committed before our flush. Rolling
            # back drops everything; the next tick will pick the rest
            # up so we just bail out gracefully.
            await db.rollback()
            log.info(
                "source %s/%s flush hit a race; deferring to next tick",
                source.kind,
                source.slug_or_url,
            )
            return 0, str(exc), 0
    return inserted, None, auto_dismissed


# ---- Bright Data keyword discovery: one run per row, imported as each lands --

ACTIVE_TICK_SECONDS = 15
# Triggers per tick. New runs are a single batched call; this only
# matters for runs started before batching (one trigger per row). A
# foreground "Poll now" never waits on a trigger.
TRIGGERS_PER_TICK = 3
# Transient trigger failures (timeout, dropped connection, 429, 5xx) are
# retried on later ticks up to this many attempts in total.
MAX_TRIGGER_ATTEMPTS = 3


def _run_of(source: JobSource) -> Optional[dict]:
    f = source.filters if isinstance(source.filters, dict) else {}
    run = f.get("run")
    return run if isinstance(run, dict) else None


def _set_filters(source: JobSource, **changes) -> None:
    f = dict(source.filters or {})
    for k, v in changes.items():
        if v is None:
            f.pop(k, None)
        else:
            f[k] = v
    source.filters = f  # reassign so SQLAlchemy sees the JSON change


async def _poll_keyword(
    db: AsyncSession, source: JobSource, *, quick: bool = False
) -> tuple[int, Optional[str]]:
    """Advance a saved keyword query by one step. No active run → queue
    ONE Bright Data snapshot covering every row (sent by the trigger
    step). Active run → check the snapshot's status and import it when
    ready. Never blocks waiting on Bright Data; the poller ticks every
    15s while a run is active and the source row shows progress
    (filters["run"]). Returns (leads inserted this step, error)."""
    from app.sources import brightdata as bd
    from app.sources.brightdata import SnapshotPending

    ctx = await _build_ctx(db, source)
    api_key = ctx.get("api_key")
    if not api_key:
        msg = "Bright Data API key required. Add one on Settings → API Keys (Bright Data)."
        source.last_polled_at = _now()
        source.last_error = msg
        return 0, msg
    cap = max(1, int(source.max_leads_per_poll or 100))
    run = _run_of(source)
    f = source.filters if isinstance(source.filters, dict) else {}

    if run is None and f.get("pending_snapshot_id"):
        # Run started by the previous single-snapshot implementation —
        # adopt it instead of paying for a new one.
        run = {
            "started_at": f.get("pending_since") or _now().isoformat(timespec="seconds"),
            "inserted": 0,
            "snapshots": [{"id": f["pending_snapshot_id"], "label": "all searches",
                           "status": "running", "leads": 0, "error": None}],
        }
        _set_filters(source, pending_snapshot_id=None, pending_since=None)

    if run is None:
        rows = bd.keyword_run_rows(source.filters)
        if not rows:
            msg = "No keyword rows saved on this source — add rows or upload the input CSV."
            source.last_polled_at = _now()
            source.last_error = msg
            return 0, msg
        # All rows go to Bright Data as ONE call (one snapshot): a job
        # that several searches match is collected — and billed — once,
        # instead of once per search. The entry starts "queued"; the
        # trigger step below sends it.
        snaps = [{"id": None, "label": f"{len(rows)} search{'es' if len(rows) != 1 else ''} · one Bright Data call",
                  "rows": rows, "searches": [bd.keyword_row_label(r) for r in rows],
                  "status": "queued", "attempts": 0, "leads": 0, "error": None}]
        run = {"started_at": _now().isoformat(timespec="seconds"),
               "inserted": 0, "snapshots": snaps}
        log.info("source %s keyword run: %d searches queued as one call", source.id, len(rows))

    # --- Trigger step: queued rows + transient failures due a retry ----
    by_label = {bd.keyword_row_label(r): r for r in bd.keyword_run_rows(source.filters)}
    budget = 0 if quick else TRIGGERS_PER_TICK
    for s in run["snapshots"]:
        if s.get("id"):
            continue
        # Runs from before retries existed: a trigger failure with an
        # empty reason was a timeout — give it the retry it deserved.
        if (s["status"] == "failed" and "attempts" not in s
                and (s.get("error") or "").rstrip().endswith("trigger failed:")):
            s["status"], s["attempts"] = "retry", 1
        if s["status"] not in ("queued", "retry") or budget <= 0:
            continue
        # Batched entry carries its rows; entries from older per-row
        # runs carry one row (or are matched back by label).
        batch = s.get("rows") or (
            [s.get("row") or by_label.get(s["label"])] if (s.get("row") or s["label"] in by_label) else []
        )
        if not batch:
            s["status"], s["error"] = "failed", "search row no longer on this source"
            continue
        budget -= 1
        s["attempts"] = int(s.get("attempts") or 0) + 1
        try:
            s["id"] = await bd.trigger_keyword_rows(
                api_key, batch, dataset_id=ctx.get("dataset_id"), limit=cap
            )
            s["status"], s["error"] = "starting", None
        except bd.TriggerTransient as exc:
            if s["attempts"] < MAX_TRIGGER_ATTEMPTS:
                s["status"] = "retry"
                s["error"] = f"{exc} — retrying (attempt {s['attempts']}/{MAX_TRIGGER_ATTEMPTS})"[:300]
            else:
                s["status"] = "failed"
                s["error"] = f"{exc} — gave up after {s['attempts']} attempts"[:300]
        except Exception as exc:  # noqa: BLE001 — one bad row mustn't sink the rest
            s["status"] = "failed"
            s["error"] = (str(exc).strip() or type(exc).__name__)[:300]

    inserted_now = 0
    try:
        started = datetime.fromisoformat(run["started_at"])
    except (KeyError, ValueError):
        started = _now()
    timed_out = _now() - started > PENDING_GIVE_UP

    for s in run["snapshots"]:
        if s["status"] in ("imported", "failed") or not s.get("id"):
            continue
        if timed_out:
            s["status"] = "failed"
            s["error"] = f"not ready after {int(PENDING_GIVE_UP.total_seconds() // 3600)}h"
            continue
        try:
            status = await bd.snapshot_status(api_key, s["id"])
        except Exception as exc:  # noqa: BLE001 — transient; retry next tick
            s["error"] = f"progress check failed: {exc}"[:300]
            continue
        if status in ("failed", "canceled"):
            s["status"] = "failed"
            s["error"] = f"Bright Data reported the run {status}"
            continue
        if status != "ready":
            s["status"] = status
            continue
        try:
            leads = await bd.download_keyword_snapshot(api_key, s["id"])
        except SnapshotPending:
            s["status"] = "ready"  # packaging; download next tick
            continue
        except Exception as exc:  # noqa: BLE001
            s["status"] = "failed"
            s["error"] = f"download failed: {exc}"[:300]
            continue
        room = cap - int(run.get("inserted") or 0)
        n = auto = 0
        if room > 0:
            n, err, auto = await _insert_leads(db, source, leads, room)
            if err is not None:
                return inserted_now, None  # race with another poll — retry next tick
        s["status"] = "imported"
        s["leads"] = n
        s["auto_dismissed"] = auto
        s["found"] = len(leads)
        run["auto_dismissed"] = int(run.get("auto_dismissed") or 0) + auto
        s["error"] = None if room > 0 else "skipped — run reached the Top # cap"
        run["inserted"] = int(run.get("inserted") or 0) + n
        inserted_now += n

    done = all(s["status"] in ("imported", "failed") for s in run["snapshots"])
    if not done:
        _set_filters(source, run=run)
        source.last_error = None
        return inserted_now, None

    failed = [s for s in run["snapshots"] if s["status"] == "failed"]
    _set_filters(source, run=None, last_run={
        "finished_at": _now().isoformat(timespec="seconds"),
        "started_at": run["started_at"],
        "searches": len(run["snapshots"]),
        "failed": len(failed),
        "leads": run["inserted"],
        "auto_dismissed": int(run.get("auto_dismissed") or 0),
    })
    source.last_polled_at = _now()
    source.last_lead_count = run["inserted"]
    if failed and len(failed) == len(run["snapshots"]):
        source.last_error = f"All {len(failed)} searches failed — first error: {failed[0]['error']}"[:1000]
        return inserted_now, source.last_error
    # Partial failures are shown on the source row, not raised.
    source.last_error = (
        f"{len(failed)} of {len(run['snapshots'])} searches failed — "
        + "; ".join(f"{s['label']}: {s['error']}" for s in failed[:3])
    )[:1000] if failed else None
    return inserted_now, None


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
    and either never polled or polled longer ago than their interval.

    MySQL DATETIME columns deserialize as naive datetimes via SQLAlchemy
    even when we wrote tz-aware ones in. We normalize to UTC before
    comparing against `now` (which is tz-aware) so the subtraction
    doesn't raise."""
    now = _now()
    rows = (
        await db.execute(
            select(JobSource).where(JobSource.deleted_at.is_(None))
        )
    ).scalars().all()
    due: list[JobSource] = []
    for s in rows:
        # A parked Bright Data snapshot is collected on the very next
        # tick regardless of schedule — and even when the source is
        # disabled, since a manual "Import now" started it and the run
        # is already paid for.
        if isinstance(s.filters, dict) and (
            s.filters.get("pending_snapshot_id") or isinstance(s.filters.get("run"), dict)
        ):
            due.append(s)
            continue
        if not s.enabled:
            continue
        if s.last_polled_at is None:
            due.append(s)
            continue
        last_polled = s.last_polled_at
        if last_polled.tzinfo is None:
            last_polled = last_polled.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(hours=max(1, s.poll_interval_hours))
        if last_polled < cutoff:
            due.append(s)
    return due


async def _tick() -> bool:
    """One poller pass. Returns True when a Bright Data keyword run is
    still in flight, so the caller ticks faster until it finishes."""
    active = False
    async with SessionLocal() as db:
        try:
            expired = await _expire_old_leads(db)
            if expired:
                log.info("Expired %d stale leads", expired)
            due = await _due_sources(db)
            for source in due:
                count, err = await poll_source(db, source)
                if _run_of(source) is not None:
                    active = True
                    # Commit per source so each search's leads show up
                    # in the inbox as soon as they're imported.
                    await db.commit()
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
    return active


async def run_forever() -> None:
    """Long-running worker. Started in app.main lifespan."""
    log.info("Source poller starting (tick=%ds)", POLL_TICK_SECONDS)
    while True:
        active = False
        try:
            active = await _tick()
        except Exception:
            log.exception("Source poller tick crashed; continuing")
        await asyncio.sleep(ACTIVE_TICK_SECONDS if active else POLL_TICK_SECONDS)


__all__ = ["run_forever", "poll_source"]
