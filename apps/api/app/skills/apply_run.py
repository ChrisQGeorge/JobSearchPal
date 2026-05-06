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
# linuxserver/chromium binds CDP to 127.0.0.1; the chromium-cdp-proxy
# sidecar forwards 0.0.0.0:9223 → 127.0.0.1:9222.
CHROMIUM_CDP_PORT = int(os.environ.get("CHROMIUM_CDP_PORT", "9223"))

MAX_ACTIONS = 50
MAX_WALL_CLOCK_SECONDS = 300


def _hash_question(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


async def _resolve_ws() -> Optional[str]:
    """Match _resolve_ws_endpoint in browser.py — discover the CDP
    WebSocket URL with Host: localhost so Chromium accepts the
    request, then rewrite the host to the address the api container
    can reach."""
    import httpx
    from urllib.parse import urlparse, urlunparse

    try:
        async with httpx.AsyncClient(
            timeout=3.0,
            headers={"Host": "localhost"},
        ) as client:
            r = await client.get(
                f"http://{CHROMIUM_HOST}:{CHROMIUM_CDP_PORT}/json/version"
            )
        if r.status_code != 200:
            return None
        ws = r.json().get("webSocketDebuggerUrl")
        if not isinstance(ws, str):
            return None
        parsed = urlparse(ws)
        return urlunparse(parsed._replace(netloc=f"{CHROMIUM_HOST}:{CHROMIUM_CDP_PORT}"))
    except Exception:
        return None


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
    """Generic agent loop. Reads the page DOM (accessibility tree),
    asks Claude what to do next, executes the action, repeats until
    the page reports a successful submission or the loop hits its
    action / wall-clock cap.

    Pauses for user help when:
      - Claude returns kind="ask_user" (novel question, etc.)
      - the page navigates somewhere clearly off-flow (login,
        captcha)
      - the action cap or wall-clock cap is reached without a
        terminal state
    """
    from playwright.async_api import async_playwright

    deadline = asyncio.get_event_loop().time() + MAX_WALL_CLOCK_SECONDS

    async with async_playwright() as p:
        try:
            ws = await _resolve_ws()
            if not ws:
                raise RuntimeError("CDP /json/version did not return a websocket URL")
            browser = await p.chromium.connect_over_cdp(
                ws,
                headers={"Host": "localhost"},
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

        # Initial screenshot so the user has something to look at on
        # /applications even before any agent steps.
        await _capture_screenshot(db, run.id, page, "00_initial.png", "initial")

        bank = await _load_question_bank(db, run.user_id)
        profile = await _load_user_profile_block(db, run.user_id, job)

        # ATS short-circuit: deterministic field-fill before the
        # generic loop starts. Whatever's left (custom questions,
        # demographics, EEO) the agent loop picks up.
        if run.ats_kind in ("greenhouse", "lever", "ashby"):
            try:
                from app.skills.apply_templates import (
                    fill_ashby_known_fields,
                    fill_greenhouse_known_fields,
                    fill_lever_known_fields,
                    parse_profile_block,
                )

                async def _logger(kind: str, payload: dict) -> None:
                    await _log_step(db, run.id, kind, payload)

                profile_dict = parse_profile_block(profile)
                if run.ats_kind == "greenhouse":
                    results = await fill_greenhouse_known_fields(
                        page, profile_dict, log_fn=_logger,
                    )
                elif run.ats_kind == "lever":
                    results = await fill_lever_known_fields(
                        page, profile_dict, log_fn=_logger,
                    )
                else:
                    results = await fill_ashby_known_fields(
                        page, profile_dict, log_fn=_logger,
                    )
                await _log_step(
                    db, run.id, "note",
                    {"detail": f"{run.ats_kind} template results",
                     "results": results},
                )
                await _capture_screenshot(
                    db, run.id, page, "01_template.png", "after-template",
                )
            except Exception as exc:
                # Templates are best-effort — fall through to the generic
                # loop on any failure rather than abandoning the run.
                await _log_step(
                    db, run.id, "note",
                    {"detail": f"{run.ats_kind} template skipped: {exc}"},
                )

        # ===== Action loop =====
        for step_n in range(1, MAX_ACTIONS + 1):
            if asyncio.get_event_loop().time() >= deadline:
                await _log_step(db, run.id, "note", {"detail": "wall-clock cap reached"})
                await _pause_for_user(
                    db, run.id,
                    "I've used up the wall-clock budget on this run. The "
                    "browser is on the page where I left off — please "
                    "review and take over to finish.",
                )
                return

            # Snapshot the page for Claude.
            try:
                ax_snapshot = await _accessibility_snapshot(page)
                page_url = page.url
                page_title = await page.title()
            except Exception as exc:
                await _log_step(db, run.id, "error", {"detail": f"DOM read failed: {exc}"})
                await _pause_for_user(
                    db, run.id,
                    "I couldn't read the page DOM. Please take over.",
                )
                return

            try:
                action = await _ask_claude_for_action(
                    user_id=run.user_id,
                    run_id=run.id,
                    job=job,
                    profile_block=profile,
                    bank=bank,
                    page_url=page_url,
                    page_title=page_title,
                    ax_snapshot=ax_snapshot,
                    step_n=step_n,
                )
            except Exception as exc:
                await _log_step(db, run.id, "error", {"detail": f"agent error: {exc}"})
                await _pause_for_user(
                    db, run.id,
                    f"I hit an error talking to Claude: {exc}. Please take over.",
                )
                return

            kind = (action or {}).get("kind", "ask_user")

            if kind == "submit":
                # Final action — log + finish run as submitted.
                await _log_step(db, run.id, "submit", {"detail": action.get("note")})
                # Best-effort: actually click the submit button if a
                # selector was given. Often the prior turn already
                # clicked submit and this one is just the model
                # confirming.
                sel = (action or {}).get("selector")
                if sel:
                    try:
                        await _safe_click(page, sel)
                    except Exception:
                        pass
                await _capture_screenshot(db, run.id, page, f"submit_{step_n:02d}.png", "submitted")
                await _finish_run(db, run.id, state="submitted")
                return

            if kind == "ask_user":
                question = (action or {}).get("question") or "I need your input to proceed."
                await _capture_screenshot(db, run.id, page, f"ask_{step_n:02d}.png", "ask_user")
                await _pause_for_user(db, run.id, question)
                return

            if kind == "navigate":
                target = (action or {}).get("url")
                if not target:
                    await _log_step(db, run.id, "note", {"detail": "navigate action missing url"})
                    continue
                await _log_step(db, run.id, "navigate", {"url": target})
                try:
                    await page.goto(target, timeout=30_000, wait_until="domcontentloaded")
                except Exception as exc:
                    await _log_step(db, run.id, "error", {"detail": f"goto failed: {exc}"})
                continue

            if kind == "click":
                sel = (action or {}).get("selector")
                if not sel:
                    await _log_step(db, run.id, "note", {"detail": "click action missing selector"})
                    continue
                try:
                    await _safe_click(page, sel)
                    await _log_step(db, run.id, "click", {"selector": sel})
                except Exception as exc:
                    await _log_step(db, run.id, "error", {"detail": f"click failed: {exc}", "selector": sel})
                continue

            if kind == "type":
                sel = (action or {}).get("selector")
                value = (action or {}).get("value", "")
                if not sel:
                    await _log_step(db, run.id, "note", {"detail": "type action missing selector"})
                    continue
                try:
                    await _safe_type(page, sel, value)
                    await _log_step(
                        db, run.id, "type",
                        {"selector": sel, "value_preview": str(value)[:200]},
                    )
                except Exception as exc:
                    await _log_step(db, run.id, "error", {"detail": f"type failed: {exc}", "selector": sel})
                continue

            if kind == "select":
                sel = (action or {}).get("selector")
                value = (action or {}).get("value", "")
                if not sel:
                    continue
                try:
                    await page.select_option(sel, value=str(value), timeout=10_000)
                    await _log_step(db, run.id, "type", {"selector": sel, "select_value": str(value)})
                except Exception as exc:
                    await _log_step(db, run.id, "error", {"detail": f"select failed: {exc}", "selector": sel})
                continue

            if kind == "check":
                sel = (action or {}).get("selector")
                if not sel:
                    continue
                try:
                    await page.check(sel, timeout=10_000)
                    await _log_step(db, run.id, "click", {"selector": sel, "check": True})
                except Exception as exc:
                    await _log_step(db, run.id, "error", {"detail": f"check failed: {exc}", "selector": sel})
                continue

            if kind == "screenshot":
                await _capture_screenshot(db, run.id, page, f"shot_{step_n:02d}.png", "agent-requested")
                continue

            if kind == "upload":
                # Render the most recent tailored doc of a given type
                # (resume / cover_letter) for the tracked job and
                # attach it. Selector must point at a file input.
                sel = (action or {}).get("selector")
                doc_type = (action or {}).get("doc_type") or "resume"
                if not sel:
                    await _log_step(db, run.id, "note", {"detail": "upload missing selector"})
                    continue
                try:
                    pdf_path = await _render_latest_doc_pdf(
                        db=db,
                        user_id=run.user_id,
                        tracked_job_id=job.id,
                        doc_type=str(doc_type),
                    )
                    if pdf_path is None:
                        await _log_step(
                            db, run.id, "note",
                            {"detail": f"no {doc_type} doc to upload — skipping"},
                        )
                        continue
                    await page.set_input_files(sel, str(pdf_path), timeout=15_000)
                    await _log_step(
                        db, run.id, "type",
                        {"selector": sel, "uploaded": str(pdf_path),
                         "doc_type": doc_type},
                    )
                except Exception as exc:
                    await _log_step(
                        db, run.id, "error",
                        {"detail": f"upload failed: {exc}", "selector": sel},
                    )
                continue

            if kind == "done":
                # Agent thinks the application is fully filled — let
                # the user verify and click submit themselves rather
                # than risk a mis-submit.
                await _capture_screenshot(db, run.id, page, f"done_{step_n:02d}.png", "ready-for-review")
                await _pause_for_user(
                    db, run.id,
                    "I've filled everything I can. Please review the form "
                    "in the streamed browser and click Submit yourself, or "
                    "tell me what to fix.",
                )
                return

            # Unknown action kind — log and bail.
            await _log_step(db, run.id, "note", {"detail": f"unknown action kind={kind}", "raw": action})
            await _pause_for_user(db, run.id, "I'm unsure what to do next. Please take over.")
            return

        # Hit the action cap.
        await _capture_screenshot(db, run.id, page, "cap.png", "action-cap")
        await _pause_for_user(
            db, run.id,
            f"I've used up the {MAX_ACTIONS}-action budget without finishing. "
            "Please review the form in the streamed browser and finish, or "
            "cancel the run.",
        )


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


async def _capture_screenshot(
    db: AsyncSession,
    run_id: int,
    page,
    name: str,
    label: str,
) -> Optional[str]:
    """Take a full-page screenshot, persist it, log a step. Best-effort."""
    try:
        png = await page.screenshot(full_page=False, timeout=10_000)
    except Exception as exc:
        await _log_step(db, run_id, "note", {"detail": f"screenshot capture failed: {exc}"})
        return None
    url = await _save_screenshot(run_id, png, name)
    await _log_step(db, run_id, "screenshot", {"label": label, "name": name}, screenshot_url=url or None)
    return url or None


async def _accessibility_snapshot(page) -> dict[str, Any]:
    """Return a trimmed accessibility-tree snapshot of the current page.

    The full Playwright a11y tree can be enormous (thousands of nodes on
    something like a Greenhouse application form). We:
      - take an `interestingOnly=True` snapshot (drops decorative nodes),
      - drop deep subtrees so the model doesn't drown,
      - strip the noisiest fields.

    The model only needs enough structure to identify form fields and
    buttons. If a real selector is needed it will look at the page or
    ask for a screenshot.
    """
    try:
        snap = await page.accessibility.snapshot(interesting_only=True)
    except Exception:
        return {"error": "accessibility_snapshot_failed"}
    if not snap:
        return {}

    MAX_NODES = 400
    counter = {"n": 0}

    def trim(node: dict[str, Any], depth: int = 0) -> Optional[dict[str, Any]]:
        if counter["n"] >= MAX_NODES:
            return None
        counter["n"] += 1
        out: dict[str, Any] = {"role": node.get("role")}
        for k in ("name", "value", "checked", "selected", "expanded",
                  "disabled", "required", "placeholder", "valuetext",
                  "description", "level", "autocomplete"):
            v = node.get(k)
            if v not in (None, "", False):
                out[k] = v
        kids = node.get("children") or []
        if kids and depth < 12:
            trimmed_kids = []
            for k in kids:
                if counter["n"] >= MAX_NODES:
                    break
                tk = trim(k, depth + 1)
                if tk:
                    trimmed_kids.append(tk)
            if trimmed_kids:
                out["children"] = trimmed_kids
        return out

    return trim(snap) or {}


async def _load_user_profile_block(
    db: AsyncSession, user_id: int, job: TrackedJob
) -> str:
    """Build a Claude-friendly text block of everything the agent might
    need to fill a form: contact info, work auth, demographics (if user
    has stored values), preferences, and the target job context.

    The agent treats this as ground truth — it should never invent a
    value not present here, and it should pause for help when the form
    asks for something not covered.
    """
    from app.models.preferences import (
        Demographics,
        JobPreferences,
        ResumeProfile,
        WorkAuthorization,
    )

    rp = (await db.execute(
        select(ResumeProfile).where(ResumeProfile.user_id == user_id)
    )).scalar_one_or_none()
    wa = (await db.execute(
        select(WorkAuthorization).where(WorkAuthorization.user_id == user_id)
    )).scalar_one_or_none()
    dm = (await db.execute(
        select(Demographics).where(Demographics.user_id == user_id)
    )).scalar_one_or_none()
    prefs = (await db.execute(
        select(JobPreferences).where(JobPreferences.user_id == user_id)
    )).scalar_one_or_none()

    lines: list[str] = []

    lines.append("# Applicant profile")
    if rp:
        lines.append("## Contact")
        for label, val in [
            ("full_name", rp.full_name),
            ("email", rp.email),
            ("phone", rp.phone),
            ("location", rp.location),
            ("linkedin_url", rp.linkedin_url),
            ("github_url", rp.github_url),
            ("portfolio_url", rp.portfolio_url),
            ("website_url", rp.website_url),
            ("headline", rp.headline),
            ("professional_summary", rp.professional_summary),
        ]:
            if val:
                lines.append(f"- {label}: {val}")

    if wa:
        lines.append("## Work authorization")
        for label, val in [
            ("current_country", wa.current_country),
            ("current_location_city", wa.current_location_city),
            ("current_location_region", wa.current_location_region),
            ("citizenship_countries", wa.citizenship_countries),
            ("work_authorization_status", wa.work_authorization_status),
            ("visa_type", wa.visa_type),
            ("visa_sponsorship_required_now", wa.visa_sponsorship_required_now),
            ("visa_sponsorship_required_future", wa.visa_sponsorship_required_future),
            ("relocation_countries_acceptable", wa.relocation_countries_acceptable),
            ("security_clearance_level", wa.security_clearance_level),
            ("security_clearance_active", wa.security_clearance_active),
        ]:
            if val not in (None, "", []):
                lines.append(f"- {label}: {val}")

    if dm:
        lines.append("## Demographics (only fill if asked AND user has provided a value)")
        for label, val in [
            ("preferred_name", dm.preferred_name),
            ("legal_first_name", dm.legal_first_name),
            ("legal_middle_name", dm.legal_middle_name),
            ("legal_last_name", dm.legal_last_name),
            ("pronouns", dm.pronouns),
            ("gender_identity", dm.gender_identity),
            ("race_ethnicity", dm.race_ethnicity),
            ("veteran_status", dm.veteran_status),
            ("disability_status", dm.disability_status),
        ]:
            if val not in (None, "", []):
                lines.append(f"- {label}: {val}")

    if prefs:
        lines.append("## Preferences")
        for label, val in [
            ("salary_preferred_target", prefs.salary_preferred_target),
            ("salary_acceptable_min", prefs.salary_acceptable_min),
            ("salary_currency", prefs.salary_currency),
            ("remote_policy_preferred", prefs.remote_policy_preferred),
            ("willing_to_relocate", prefs.willing_to_relocate),
            ("earliest_start_date", prefs.earliest_start_date),
            ("notice_period_weeks", prefs.notice_period_weeks),
        ]:
            if val not in (None, "", []):
                lines.append(f"- {label}: {val}")

    lines.append("# Target job")
    lines.append(f"- title: {job.title}")
    if job.location:
        lines.append(f"- location: {job.location}")
    if job.source_url:
        lines.append(f"- url: {job.source_url}")
    if job.remote_policy:
        lines.append(f"- remote_policy: {job.remote_policy}")
    if job.experience_level:
        lines.append(f"- experience_level: {job.experience_level}")

    return "\n".join(lines)


_AGENT_SYSTEM_PROMPT = """You are the Job Search Pal Companion driving a real \
Chromium browser through Playwright on behalf of a user filling out a job \
application. On every turn you receive:

  1. The page URL + title.
  2. A trimmed accessibility tree of the current DOM.
  3. The user's profile block (contact, work auth, prefs).
  4. A question bank of {hash: answer} entries the user has previously confirmed.

Return EXACTLY one JSON object on a single line — no prose, no markdown \
fences, no explanation — with this shape:

  {"kind": "navigate"|"click"|"type"|"select"|"check"|"upload"|"screenshot"|"submit"|"ask_user"|"done",
   "selector": "<CSS selector when applicable>",
   "value": "<string for type/select>",
   "url": "<url for navigate>",
   "doc_type": "<resume|cover_letter — required for upload>",
   "question": "<prompt for ask_user>",
   "note": "<optional 1-line rationale>"}

For file uploads (resume / cover-letter): emit kind=upload with the
file-input's selector and doc_type. The runner renders the user's
most-recent matching tailored document to PDF and attaches it.

Rules:
- Prefer robust selectors: `[name=...]`, `[id=...]`, `[aria-label=...]`. \
Avoid brittle nth-child positions.
- Never invent personal info. If the form asks for something not in the \
profile and not in the question bank, return ask_user with the verbatim \
question text.
- Do NOT click the final "Submit application" button unless every required \
field is filled and the page clearly shows the user wanted to submit. \
Prefer kind=done — let the human click submit.
- If you see a CAPTCHA, login wall, OAuth popup, or any "are you human" \
gate, return ask_user describing what you see.
- If the page is already a confirmation/thank-you page, return kind=submit \
with note explaining what you saw.
- Only one action per turn. The next turn will give you the new page state.
"""


async def _ask_claude_for_action(
    *,
    user_id: int,
    run_id: int,
    job: TrackedJob,
    profile_block: str,
    bank: dict[str, str],
    page_url: str,
    page_title: str,
    ax_snapshot: dict[str, Any],
    step_n: int,
) -> dict[str, Any]:
    """Ask Claude what to do next. Returns a parsed action dict.

    Falls back to ask_user if the response can't be parsed as JSON."""
    from app.skills.runner import run_claude_prompt

    bank_lines: list[str] = []
    for h, a in list(bank.items())[:200]:
        bank_lines.append(f"  {h[:10]}: {a[:300]}")
    bank_block = "\n".join(bank_lines) if bank_lines else "  (empty)"

    snapshot_json = json.dumps(ax_snapshot, ensure_ascii=False)
    if len(snapshot_json) > 80_000:
        snapshot_json = snapshot_json[:80_000] + "...(truncated)"

    prompt = (
        f"Step #{step_n}.\n\n"
        f"PAGE URL: {page_url}\n"
        f"PAGE TITLE: {page_title}\n\n"
        f"PROFILE:\n{profile_block}\n\n"
        f"QUESTION BANK (hash → answer; pull from here when a question matches):\n"
        f"{bank_block}\n\n"
        f"ACCESSIBILITY TREE (trimmed):\n{snapshot_json}\n\n"
        "What is the single next action? Respond with the JSON object only."
    )

    try:
        result = await run_claude_prompt(
            prompt=prompt,
            output_format="json",
            system_prompt_append=_AGENT_SYSTEM_PROMPT,
            timeout_seconds=90,
        )
    except Exception as exc:
        log.warning("apply_run %d: claude call failed: %s", run_id, exc)
        return {
            "kind": "ask_user",
            "question": f"My agent loop hit an error talking to Claude: {exc}",
        }

    text = (result.result or "").strip()
    # Strip optional markdown fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Sometimes Claude returns extra prose after the JSON; grab the first {...}.
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {
        "kind": "ask_user",
        "question": (
            "I couldn't decide on a next action — Claude returned an "
            "un-parseable response. Please take over."
        ),
    }


async def _safe_click(page, selector: str) -> None:
    """Click with a sensible timeout; let the caller catch the exception
    and decide whether to retry / pause."""
    await page.wait_for_selector(selector, timeout=10_000, state="visible")
    await page.click(selector, timeout=10_000)


async def _safe_type(page, selector: str, value: Any) -> None:
    """Fill an input — preferred over .type() because it handles existing
    text, file inputs, and contenteditable nodes via a single API."""
    await page.wait_for_selector(selector, timeout=10_000)
    await page.fill(selector, str(value), timeout=10_000)


async def _render_latest_doc_pdf(
    *,
    db: AsyncSession,
    user_id: int,
    tracked_job_id: int,
    doc_type: str,
):
    """Find the most recent non-empty tailored doc of `doc_type`
    linked to this tracked job and render it to PDF. Returns the
    path or None if nothing matches."""
    from app.models.documents import GeneratedDocument
    from app.skills.pdf_render import render_document_to_pdf

    stmt = (
        select(GeneratedDocument)
        .where(
            GeneratedDocument.user_id == user_id,
            GeneratedDocument.tracked_job_id == tracked_job_id,
            GeneratedDocument.doc_type == doc_type,
            GeneratedDocument.deleted_at.is_(None),
        )
        .order_by(GeneratedDocument.updated_at.desc())
        .limit(1)
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if doc is None or not (doc.content_md or "").strip():
        # Fall back to any user-level doc of that type (e.g. a generic
        # resume not yet tailored). Better than failing the upload.
        stmt2 = (
            select(GeneratedDocument)
            .where(
                GeneratedDocument.user_id == user_id,
                GeneratedDocument.doc_type == doc_type,
                GeneratedDocument.deleted_at.is_(None),
            )
            .order_by(GeneratedDocument.updated_at.desc())
            .limit(1)
        )
        doc = (await db.execute(stmt2)).scalar_one_or_none()
    if doc is None or not (doc.content_md or "").strip():
        return None
    return await render_document_to_pdf(doc.id)
