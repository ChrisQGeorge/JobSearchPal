"""Import a Bright Data export file (JSON array / JSON Lines) into a
source's lead inbox — the same path a finished API snapshot takes:
record → lead mapping, the source's own filters, dedupe against leads
already on the source, and the user's auto-dismiss keyword filters.

Use it when Bright Data finished a collection the app didn't pick up
(e.g. the trigger reply was lost) — the data is already paid for, so
it's imported instead of re-running the search.

Runs in the background: the upload is spooled to disk, parsed in a
worker thread (the event loop stays free for browsing), and inserted in
chunks on the background DB pool. Progress lives in memory (UPLOADS),
polled by the leads page; it's gone after a restart, the leads aren't.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

CHUNK = 500
UPLOAD_DIR = "/tmp/jsp-lead-uploads"

# source_id → progress dict (see _new_progress).
UPLOADS: dict[int, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _new_progress(filename: str, size: int) -> dict[str, Any]:
    return {
        "status": "importing",  # importing | done | failed
        "filename": filename,
        "bytes": size,
        "started_at": _now_iso(),
        "finished_at": None,
        "records": 0,       # records read from the file
        "not_jobs": 0,      # error rows / records that didn't map to a job
        "leads": 0,         # new leads added to the inbox
        "auto_dismissed": 0,
        "duplicates_or_filtered": 0,
        "error": None,
    }


def is_running(source_id: int) -> bool:
    p = UPLOADS.get(source_id)
    return bool(p and p["status"] == "importing")


def mapper_for(kind: str):
    from app.sources import brightdata as bd

    if kind == "brightdata_glassdoor":
        return bd._to_lead_glassdoor
    if kind in ("brightdata_keyword", "brightdata_linkedin"):
        return bd._to_lead_linkedin
    return None


async def run_import(source_id: int, path: str) -> None:
    """Background task. Never raises; outcome lands in UPLOADS."""
    from sqlalchemy import select

    from app.core.database import BgSessionLocal
    from app.core.responsiveness import yield_to_requests
    from app.models.sources import JobLead, JobSource
    from app.sources import brightdata as bd
    from app.sources.poller import _insert_leads

    prog = UPLOADS[source_id]
    fh = None
    try:
        async with BgSessionLocal() as db:
            source = await db.get(JobSource, source_id)
            if source is None:
                raise RuntimeError("Source no longer exists.")
            to_lead = mapper_for(source.kind)
            existing = set(
                (
                    await db.execute(
                        select(JobLead.external_id).where(JobLead.source_id == source.id)
                    )
                ).scalars().all()
            )
            await db.commit()  # release the connection while parsing

            fh = open(path, "rb")
            records = bd.iter_export_records(fh)

            def next_batch() -> tuple[list[dict], int, int]:
                # Runs in a worker thread: JSON decoding + mapping are CPU work.
                leads, read, bad = [], 0, 0
                for rec in records:
                    read += 1
                    lead = to_lead(rec) if isinstance(rec, dict) and not rec.get("error") else None
                    if lead is None:
                        bad += 1
                    else:
                        leads.append(lead)
                    if read >= CHUNK:
                        break
                return leads, read, bad

            while True:
                leads, read, bad = await asyncio.to_thread(next_batch)
                if read == 0:
                    break
                prog["records"] += read
                prog["not_jobs"] += bad
                if leads:
                    await yield_to_requests()
                    n, err, auto = await _insert_leads(
                        db, source, leads, cap=10**9, existing=existing
                    )
                    if err is not None:
                        raise RuntimeError(f"Database conflict while inserting: {err}")
                    await db.commit()
                    prog["leads"] += n
                    prog["auto_dismissed"] += auto
                    prog["duplicates_or_filtered"] += len(leads) - n - auto
                await asyncio.sleep(0)
        prog["status"] = "done"
        if prog["records"] == 0:
            prog["status"] = "failed"
            prog["error"] = "The file contained no records."
    except Exception as exc:  # noqa: BLE001
        log.exception("lead file import failed for source %s", source_id)
        prog["status"] = "failed"
        prog["error"] = (
            f"{type(exc).__name__}: {str(exc).strip() or 'no detail'} — stopped after "
            f"{prog['records']} records ({prog['leads']} leads were already added and are kept)."
        )
    finally:
        prog["finished_at"] = _now_iso()
        if fh is not None:
            fh.close()
        try:
            os.remove(path)
        except OSError:
            pass


def spool_path(source_id: int) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return os.path.join(UPLOAD_DIR, f"source-{source_id}-{ts}.json")


def start(source_id: int, path: str, filename: str, size: int) -> dict[str, Any]:
    UPLOADS[source_id] = _new_progress(filename, size)
    task = asyncio.get_running_loop().create_task(run_import(source_id, path))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return UPLOADS[source_id]


# Strong refs so background tasks aren't garbage-collected mid-run.
_TASKS: set[asyncio.Task] = set()


def progress(source_id: int) -> Optional[dict[str, Any]]:
    return UPLOADS.get(source_id)
