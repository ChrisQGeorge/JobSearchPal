"""Companion-driven application-run handler (R10/R11).

Picks up an `apply_run` queue row, opens a Playwright session against
the chromium container's CDP endpoint, walks the user's tracked job's
source_url, and tries to fill out the application form.

Design notes:

  - Stage 1 (R10): generic agent loop. Every page transition produces
    a DOM accessibility-tree snapshot + screenshot, hands them to
    Claude with the question-bank inline, Claude returns one action,
    we execute it, repeat. Hard-cap at 50 actions / 5 min.
  - Stage 2 (R11): per-ATS template can short-circuit the loop when
    the URL matches a known shape (greenhouse / lever / ashby /
    workable). The template knows the field selectors and only falls
    back to the generic loop on unknown questions.
  - On any "I don't have an answer to this" — the run flips to
    `awaiting_user`, the question is stored on the row, the queue
    worker exits cleanly. The user types an answer in the UI, the
    /answer endpoint flips state back to running and the worker
    re-claims the row on the next tick.

This file ships the *scaffolding* — concrete Greenhouse selectors etc.
land in subsequent commits. The generic loop is intentionally small
so it's easy to follow and replace.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.applications import (
    ApplicationRun,
    ApplicationRunStep,
    QuestionAnswer,
)
from app.models.jobs import JobFetchQueue, TrackedJob

log = logging.getLogger(__name__)

CHROMIUM_HOST = os.environ.get("CHROMIUM_HOST", "chromium")
CHROMIUM_CDP_PORT = int(os.environ.get("CHROMIUM_CDP_PORT", "9222"))

MAX_ACTIONS = 50
MAX_WALL_CLOCK_SECONDS = 300


def _hash_question(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


async def _detect_ats(url: str) -> Optional[str]:
    u = url.lower()
    if "boards.greenhouse.io" in u or "greenhouse.io" in u:
        return "greenhouse"
    if "jobs.lever.co" in u or "lever.co" in u:
        return "lever"
    if "jobs.ashbyhq.com" in u or "ashbyhq.com" in u:
        return "ashby"
    if "apply.workable.com" in u or "workable.com" in u:
        return "workable"
    return None


async def _log_step(
    db: AsyncSession,
    run_id: int,
    kind: str,
    payload: Optional[dict] = None,
    screenshot_url: Optional[str] = None,
) -> None:
    db.add(
        ApplicationRunStep(
            run_id=run_id,
            ts=datetime.now(tz=timezone.utc),
            kind=kind,
            payload=payload,
            screenshot_url=screenshot_url,
        )
    )
    await db.commit()


async def _load_question_bank(
    db: AsyncSession, user_id: int
) -> dict[str, str]:
    rows = (
        await db.execute(
            select(QuestionAnswer.question_hash, QuestionAnswer.answer).where(
                QuestionAnswer.user_id == user_id
            )
        )
    ).all()
    return {h: a for (h, a) in rows}


async def _pause_for_user(
    db: AsyncSession,
    run_id: int,
    question: str,
) -> None:
    """Flip the run to awaiting_user with the question recorded. The
    worker's caller observes state != running and exits — the user
    will resolve via /api/v1/application-runs/{id}/answer."""
    h = _hash_question(question)
    row = (
        await db.execute(select(ApplicationRun).where(ApplicationRun.id == run_id))
    ).scalar_one_or_none()
    if row is None:
        return
    row.state = "awaiting_user"
    row.pending_question = question[:8000]
    row.pending_question_hash = h
    db.add(
        ApplicationRunStep(
            run_id=run_id,
            ts=datetime.now(tz=timezone.utc),
            kind="ask_user",
            payload={"question": question[:1000], "hash": h},
        )
    )
    await db.commit()


async def _finish_run(
    db: AsyncSession,
    run_id: int,
    *,
    state: str,
    error: Optional[str] = None,
) -> None:
    row = (
        await db.execute(select(ApplicationRun).where(ApplicationRun.id == run_id))
    ).scalar_one_or_none()
    if row is None:
        return
    row.state = state
    row.finished_at = datetime.now(tz=timezone.utc)
    if error is not None:
        row.error_message = error[:2000]
    await db.commit()


async def handle_apply_run(item: JobFetchQueue) -> None:
    """Top-level dispatcher for a single apply_run queue row."""
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
        run_id = payload.get("application_run_id")
        if not run_id:
            row.state = "error"
            row.error_message = "apply_run task missing application_run_id"
            await db.commit()
            return

        run = (
            await db.execute(
                select(ApplicationRun).where(ApplicationRun.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None:
            row.state = "error"
            row.error_message = f"ApplicationRun {run_id} not found"
            await db.commit()
            return

        # If the user resolved a pending question, the run flipped back
        # to running before this re-tick. If they haven't, we shouldn't
        # be here yet — exit and let the queue re-poll later.
        if run.state == "awaiting_user":
            row.state = "queued"  # park for next tick
            await db.commit()
            return
        if run.state in ("submitted", "failed", "cancelled"):
            row.state = "done"
            await db.commit()
            return

        job = (
            await db.execute(
                select(TrackedJob).where(TrackedJob.id == run.tracked_job_id)
            )
        ).scalar_one_or_none()
        if job is None or not job.source_url:
            await _finish_run(db, run.id, state="failed", error="Tracked job or source_url missing.")
            row.state = "error"
            row.error_message = "Tracked job missing"
            await db.commit()
            return

        run.state = "running"
        if run.started_at is None:
            run.started_at = datetime.now(tz=timezone.utc)
        run.ats_kind = await _detect_ats(job.source_url) or run.ats_kind
        if run.ats_kind:
            run.tier = "ats"
        await db.commit()

        try:
            await _drive_browser(db, run, job)
        except ClaudeCodeError as exc:
            log.warning("apply_run %d Claude error: %s", run.id, exc)
            await _finish_run(db, run.id, state="failed", error=str(exc))
        except Exception as exc:  # pragma: no cover
            log.exception("apply_run %d unhandled error", run.id)
            await _finish_run(db, run.id, state="failed", error=f"{type(exc).__name__}: {exc}")

        # Mark the queue row done either way — the run row carries the
        # nuanced state.
        row = (
            await db.execute(
                select(JobFetchQueue).where(JobFetchQueue.id == item.id)
            )
        ).scalar_one_or_none()
        if row is not None:
            row.state = "done"
            row.result = {"application_run_id": run.id}
            await db.commit()


async def _drive_browser(
    db: AsyncSession, run: ApplicationRun, job: TrackedJob
) -> None:
    """The actual loop. Connects to chromium over CDP, navigates,
    fills what it can from the question bank, pauses on novel
    questions. Bails after MAX_ACTIONS or wall-clock cap.

    This is the R10 scaffold — production-grade ATS templates layer
    on top in R11."""
    from playwright.async_api import async_playwright

    deadline = asyncio.get_event_loop().time() + MAX_WALL_CLOCK_SECONDS

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(
                f"http://{CHROMIUM_HOST}:{CHROMIUM_CDP_PORT}"
            )
        except Exception as exc:
            await _log_step(
                db, run.id, "error",
                {"detail": f"CDP connect failed: {exc}. Is the chromium service up?"},
            )
            await _finish_run(db, run.id, state="failed", error=f"CDP connect failed: {exc}")
            return

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        await _log_step(db, run.id, "navigate", {"url": job.source_url})
        try:
            await page.goto(job.source_url, timeout=30_000, wait_until="domcontentloaded")
        except Exception as exc:
            await _log_step(db, run.id, "error", {"detail": f"navigate failed: {exc}"})
            await _finish_run(db, run.id, state="failed", error=f"navigate failed: {exc}")
            return

        # Take an initial screenshot so the user has something to look
        # at on /applications even before the agent does anything.
        try:
            png = await page.screenshot(full_page=False, timeout=10_000)
            screenshot_path = await _save_screenshot(run.id, png, "00_initial.png")
            await _log_step(db, run.id, "screenshot", {"label": "initial"}, screenshot_url=screenshot_path)
        except Exception:
            pass

        bank = await _load_question_bank(db, run.user_id)

        # === Generic R10 placeholder ===
        # In this first cut, the loop only logs the page state and
        # then asks the user to take over via the /browser page. The
        # actual action loop (DOM read → Claude → click/type → repeat)
        # lands in a follow-up commit. Stopping here is intentional:
        # the user can drive manually in the streamed window today,
        # and the queueing + tracking + question-bank scaffolding is
        # all wired so the loop body can drop in cleanly.

        await _log_step(
            db,
            run.id,
            "note",
            {
                "detail": (
                    "Page loaded. Generic agent loop is not yet "
                    "implemented — take over manually in the /browser "
                    "tab and submit, or wait for an ATS-aware "
                    "template to ship for this site."
                ),
                "ats_kind": run.ats_kind,
                "question_bank_size": len(bank),
                "deadline_seconds_remaining": max(
                    0, int(deadline - asyncio.get_event_loop().time())
                ),
            },
        )

        # Hand the wheel to the user.
        await _pause_for_user(
            db,
            run.id,
            (
                "I've loaded the application page in your streamed "
                "browser. The generic agent loop isn't wired yet — "
                "open /browser to fill the form yourself, or wait for "
                f"the ATS-specific {run.ats_kind or 'generic'} template "
                "to ship. Reply with anything to acknowledge and close "
                "this run."
            ),
        )

        # Don't close the browser — leaving the page on screen is the
        # whole point. The chromium container persists; the user takes
        # over from here.


async def _save_screenshot(run_id: int, png_bytes: bytes, name: str) -> str:
    """Drop a screenshot into /app/uploads/applications/<run_id>/<name>
    and return the URL the frontend can load via the existing uploads
    static handler. Best-effort — failure logs and returns empty."""
    try:
        from pathlib import Path

        base = Path("/app/uploads/applications") / str(run_id)
        base.mkdir(parents=True, exist_ok=True)
        target = base / name
        target.write_bytes(png_bytes)
        return f"/api/v1/application-runs/{run_id}/screenshot/{name}"
    except Exception:
        return ""
