"""Browser-piped automation surface (R10).

Three concerns wrapped in one router:

  /api/v1/browser/info       — stream URL + status (single-user)
  /api/v1/browser/stream     — websocket proxy from Next → KasmVNC
  /api/v1/browser/navigate   — POST a URL, Chromium goes there
  /api/v1/browser/take-over  — soft mutex toggles
  /api/v1/browser/release
  /api/v1/browser/screenshot — debug helper, returns a PNG

  /api/v1/application-runs   — list + open one + answer pending Q
  /api/v1/application-runs/start — start an apply_run for a tracked job

  /api/v1/question-bank      — CRUD for QuestionAnswer

The Chromium service runs in its own container and is unreachable
from the host. Both the noVNC stream and the CDP control plane are
proxied through this api with cookie auth so only the logged-in user
can touch them."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.applications import (
    ApplicationRun,
    ApplicationRunStep,
    QuestionAnswer,
)
from app.models.jobs import JobFetchQueue, TrackedJob
from app.models.user import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/browser", tags=["browser"])
runs_router = APIRouter(prefix="/application-runs", tags=["application-runs"])
qa_router = APIRouter(prefix="/question-bank", tags=["question-bank"])


# Inside the docker-compose network the chromium container resolves to
# its service name. KasmVNC's web app listens on port 3000, the CDP
# debugger on 9222.
CHROMIUM_HOST = os.environ.get("CHROMIUM_HOST", "chromium")
CHROMIUM_VNC_PORT = int(os.environ.get("CHROMIUM_VNC_PORT", "3000"))
# linuxserver/chromium binds CDP to 127.0.0.1 only; the
# `chromium-cdp-proxy` sidecar (socat in the same netns) forwards
# 0.0.0.0:9223 → 127.0.0.1:9222 so the api container can reach it.
CHROMIUM_CDP_PORT = int(os.environ.get("CHROMIUM_CDP_PORT", "9223"))
CHROMIUM_VNC_PASSWORD = os.environ.get("CHROMIUM_VNC_PASSWORD", "jobsearchpal")


# ---------- soft mutex ------------------------------------------------------
#
# A single in-memory flag tracks who's "driving" the browser — user or
# Companion. Both control planes always work regardless (this is a
# hint, not a hard lock). Persists for the lifetime of the api process,
# which is fine for a single-user deployment.
_DRIVER: dict[str, str] = {"who": "user"}


def _driver_status() -> dict[str, str]:
    return {"driver": _DRIVER.get("who", "user")}


# ---------- /info -----------------------------------------------------------


class BrowserInfoOut(BaseModel):
    cdp_reachable: bool
    vnc_reachable: bool
    driver: str
    chromium_host: str
    note: Optional[str] = None


async def _check_cdp() -> bool:
    """Quick liveness check on the chromium container's CDP endpoint.

    Chromium's CDP rejects non-loopback Host headers as a CSRF
    defense ("Host header is specified and is not an IP address or
    localhost"). The cdp-proxy sidecar forwards the port but
    can't rewrite the request, so we send `Host: localhost` ourselves."""
    try:
        async with httpx.AsyncClient(
            timeout=3.0,
            headers={"Host": "localhost"},
        ) as client:
            r = await client.get(
                f"http://{CHROMIUM_HOST}:{CHROMIUM_CDP_PORT}/json/version"
            )
        return r.status_code == 200
    except Exception:
        return False


async def _resolve_ws_endpoint() -> Optional[str]:
    """Hit /json/version with Host: localhost, pull the
    `webSocketDebuggerUrl`, replace Chromium's loopback host:port
    with our reachable `chromium:9223`. Playwright's connect_over_cdp
    on the HTTP root re-uses the Host header on the WS upgrade and
    drops the port, which fails — passing a fully-formed WS URL
    sidesteps that path entirely."""
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
        data = r.json()
        ws = data.get("webSocketDebuggerUrl")
        if not isinstance(ws, str):
            return None
        # Replace whatever host:port Chromium reported with the address
        # the api container can actually reach.
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(ws)
        rewritten = parsed._replace(netloc=f"{CHROMIUM_HOST}:{CHROMIUM_CDP_PORT}")
        return urlunparse(rewritten)
    except Exception:
        return None


async def _check_vnc() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"http://{CHROMIUM_HOST}:{CHROMIUM_VNC_PORT}/", follow_redirects=True)
        return r.status_code < 500
    except Exception:
        return False


@router.get("/info", response_model=BrowserInfoOut)
async def get_info(
    user: User = Depends(get_current_user),
) -> BrowserInfoOut:
    cdp = await _check_cdp()
    vnc = await _check_vnc()
    note = None
    if not (cdp and vnc):
        note = (
            "The chromium service isn't reachable yet. Make sure the "
            "`chromium` compose service is running: "
            "`docker compose up -d chromium`."
        )
    return BrowserInfoOut(
        cdp_reachable=cdp,
        vnc_reachable=vnc,
        driver=_driver_status()["driver"],
        chromium_host=CHROMIUM_HOST,
        note=note,
    )


# ---------- soft mutex toggles ----------------------------------------------


@router.post("/take-over")
async def take_over(user: User = Depends(get_current_user)) -> dict[str, str]:
    _DRIVER["who"] = "user"
    return _driver_status()


@router.post("/release")
async def release(user: User = Depends(get_current_user)) -> dict[str, str]:
    _DRIVER["who"] = "companion"
    return _driver_status()


# ---------- navigate --------------------------------------------------------


class NavigateIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@router.post("/navigate")
async def navigate(
    payload: NavigateIn,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Navigate the streamed Chromium to `url`. Uses Playwright over
    CDP. Returns the page title on success."""
    target = payload.url.strip()
    if not (target.startswith("http://") or target.startswith("https://")):
        target = "https://" + target
    try:
        # Lazy import — playwright is only installed once R10 ships and
        # the chromium service is up, so don't pull it at module load.
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            ws = await _resolve_ws_endpoint()
            if not ws:
                raise HTTPException(
                    status_code=502,
                    detail="Couldn't resolve Chromium CDP endpoint.",
                )
            browser = await p.chromium.connect_over_cdp(
                ws,
                headers={"Host": "localhost"},
            )
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto(target, timeout=30_000)
            title = await page.title()
            await browser.close()
        return {"url": target, "title": title}
    except Exception as exc:  # noqa: BLE001
        log.warning("Browser navigate failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Couldn't drive the browser: {exc}",
        )


# ---------- screenshot ------------------------------------------------------


@router.get("/screenshot")
async def screenshot(user: User = Depends(get_current_user)) -> Response:
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            ws = await _resolve_ws_endpoint()
            if not ws:
                raise HTTPException(
                    status_code=502,
                    detail="Couldn't resolve Chromium CDP endpoint.",
                )
            browser = await p.chromium.connect_over_cdp(
                ws,
                headers={"Host": "localhost"},
            )
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            png = await page.screenshot(type="png", full_page=False)
            await browser.close()
        return Response(content=png, media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Screenshot failed: {exc}")


# ---------- stream proxy (websocket) ----------------------------------------
#
# KasmVNC speaks WebSocket on /websockify by default. We accept the
# user's WebSocket (cookie-auth at handshake), open a second one to
# the chromium container, and pump bytes both ways. Single-user
# deployment so we don't worry about multiplexing.


@router.websocket("/stream")
async def browser_stream(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    # Cookie-auth on the WebSocket. Mirrors get_current_user but gentle
    # on failure (close instead of raise).
    from app.core.deps import _resolve_user_from_request

    try:
        user = await _resolve_user_from_request(websocket, db)
    except Exception:
        await websocket.close(code=4401)
        return
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept(subprotocol="binary")
    upstream_url = f"ws://{CHROMIUM_HOST}:{CHROMIUM_VNC_PORT}/websockify"
    try:
        import websockets

        async with websockets.connect(
            upstream_url, subprotocols=["binary"], max_size=None
        ) as upstream:

            async def _client_to_upstream() -> None:
                while True:
                    msg = await websocket.receive_bytes()
                    await upstream.send(msg)

            async def _upstream_to_client() -> None:
                async for msg in upstream:
                    if isinstance(msg, bytes):
                        await websocket.send_bytes(msg)
                    else:
                        await websocket.send_text(msg)

            tasks = [
                asyncio.create_task(_client_to_upstream()),
                asyncio.create_task(_upstream_to_client()),
            ]
            try:
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_EXCEPTION
                )
                for t in pending:
                    t.cancel()
            finally:
                for t in tasks:
                    t.cancel()
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover
        log.info("browser stream error: %s", exc)
        try:
            await websocket.close()
        except Exception:
            pass


# ---------- application-run endpoints ---------------------------------------


class ApplicationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tracked_job_id: int
    tier: str
    state: str
    ats_kind: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    queue_id: Optional[int] = None
    cost_usd: Optional[float] = None
    error_message: Optional[str] = None
    pending_question: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ApplicationRunStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ts: datetime
    kind: str
    payload: Optional[dict] = None
    screenshot_url: Optional[str] = None


class ApplicationRunDetailOut(ApplicationRunOut):
    steps: list[ApplicationRunStepOut] = []
    tracked_job_title: Optional[str] = None


class StartRunIn(BaseModel):
    tracked_job_id: int


class StartRunOut(BaseModel):
    run_id: int
    queue_id: int


@runs_router.get("", response_model=list[ApplicationRunOut])
async def list_runs(
    state: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ApplicationRun]:
    stmt = (
        select(ApplicationRun)
        .where(ApplicationRun.user_id == user.id)
        .order_by(desc(ApplicationRun.created_at))
        .limit(limit)
    )
    if state:
        stmt = stmt.where(ApplicationRun.state == state)
    return list((await db.execute(stmt)).scalars().all())


@runs_router.get("/{run_id:int}/screenshot/{name}")
async def get_run_screenshot(
    run_id: int,
    name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Serve a screenshot file written by the apply_run handler under
    `/app/uploads/applications/<run_id>/<name>`. Cookie-auth gates
    access; filenames are restricted to a safe charset to prevent
    directory traversal."""
    from pathlib import Path

    if not re.fullmatch(r"[\w.\-]+\.(png|jpg|jpeg)", name):
        raise HTTPException(status_code=400, detail="Bad filename")
    row = (
        await db.execute(
            select(ApplicationRun).where(
                ApplicationRun.id == run_id,
                ApplicationRun.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    p = Path("/app/uploads/applications") / str(run_id) / name
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return Response(content=p.read_bytes(), media_type="image/png")


@runs_router.get("/{run_id:int}", response_model=ApplicationRunDetailOut)
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApplicationRunDetailOut:
    row = (
        await db.execute(
            select(ApplicationRun).where(
                ApplicationRun.id == run_id,
                ApplicationRun.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    steps = list(
        (
            await db.execute(
                select(ApplicationRunStep)
                .where(ApplicationRunStep.run_id == run_id)
                .order_by(ApplicationRunStep.ts.asc(), ApplicationRunStep.id.asc())
            )
        ).scalars().all()
    )
    job = (
        await db.execute(
            select(TrackedJob.title).where(TrackedJob.id == row.tracked_job_id)
        )
    ).first()
    out = ApplicationRunDetailOut.model_validate(row)
    out.steps = [ApplicationRunStepOut.model_validate(s) for s in steps]
    out.tracked_job_title = job[0] if job else None
    return out


@runs_router.post("/start", response_model=StartRunOut, status_code=status.HTTP_201_CREATED)
async def start_run(
    payload: StartRunIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StartRunOut:
    """Kick off a Companion-driven application attempt for `tracked_job_id`.
    Creates an ApplicationRun row + a `apply_run` queue row that the
    worker picks up. Refuses to start if the tracked job's status is
    already past `to_review` (already applied / responded / etc.) so
    a stale browser tab can't accidentally re-apply."""
    job = (
        await db.execute(
            select(TrackedJob).where(
                TrackedJob.id == payload.tracked_job_id,
                TrackedJob.user_id == user.id,
                TrackedJob.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Tracked job not found")

    blocked = {
        "applied",
        "responded",
        "screening",
        "interviewing",
        "assessment",
        "offer",
        "won",
        "withdrawn",
    }
    if job.status in blocked:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job is at status='{job.status}' — apply_run refuses to "
                "submit a duplicate application."
            ),
        )
    if not job.source_url:
        raise HTTPException(
            status_code=422,
            detail="Tracked job has no source_url to drive the browser to.",
        )

    run = ApplicationRun(
        user_id=user.id,
        tracked_job_id=job.id,
        tier="generic",
        state="queued",
    )
    db.add(run)
    await db.flush()

    queued = JobFetchQueue(
        user_id=user.id,
        kind="apply_run",
        label=f"Apply → {job.title[:80]}"[:512],
        url=job.source_url,
        payload={"application_run_id": run.id, "tracked_job_id": job.id},
        state="queued",
    )
    db.add(queued)
    await db.flush()
    run.queue_id = queued.id
    await db.commit()
    return StartRunOut(run_id=run.id, queue_id=queued.id)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)
    save_to_bank: bool = True


@runs_router.post("/{run_id:int}/answer")
async def answer_pending(
    run_id: int,
    payload: AnswerIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Submit the user's answer for a run that's in state=awaiting_user.
    Stores in the question-bank (idempotent on hash), flips the run
    back to state=running, and lets the worker resume."""
    row = (
        await db.execute(
            select(ApplicationRun).where(
                ApplicationRun.id == run_id,
                ApplicationRun.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row.state != "awaiting_user" or not row.pending_question_hash:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in state='{row.state}', not awaiting an answer.",
        )

    if payload.save_to_bank and row.pending_question:
        existing = (
            await db.execute(
                select(QuestionAnswer).where(
                    QuestionAnswer.user_id == user.id,
                    QuestionAnswer.question_hash == row.pending_question_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                QuestionAnswer(
                    user_id=user.id,
                    question_hash=row.pending_question_hash,
                    question_text=row.pending_question[:2000],
                    answer=payload.answer,
                    source="user",
                    last_used_at=datetime.now(tz=timezone.utc),
                )
            )
        else:
            existing.answer = payload.answer
            existing.last_used_at = datetime.now(tz=timezone.utc)

    db.add(
        ApplicationRunStep(
            run_id=row.id,
            ts=datetime.now(tz=timezone.utc),
            kind="answer",
            payload={
                "question": row.pending_question,
                "answer_preview": payload.answer[:200],
            },
        )
    )
    row.pending_question = None
    row.pending_question_hash = None
    row.state = "running"
    await db.commit()
    return {"state": row.state}


@runs_router.post("/{run_id:int}/cancel")
async def cancel_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(ApplicationRun).where(
                ApplicationRun.id == run_id,
                ApplicationRun.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row.state in ("submitted", "failed", "cancelled"):
        return {"state": row.state}
    row.state = "cancelled"
    row.finished_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return {"state": row.state}


# ---------- question-bank ---------------------------------------------------


class QuestionAnswerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    question_text: str
    answer: str
    source: str
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class QuestionAnswerIn(BaseModel):
    question_text: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)
    source: Optional[str] = None


def _hash_question(text: str) -> str:
    import hashlib
    import re

    norm = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


@qa_router.get("", response_model=list[QuestionAnswerOut])
async def list_question_answers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[QuestionAnswer]:
    stmt = (
        select(QuestionAnswer)
        .where(QuestionAnswer.user_id == user.id)
        .order_by(desc(func.coalesce(QuestionAnswer.last_used_at, QuestionAnswer.created_at)))
    )
    return list((await db.execute(stmt)).scalars().all())


@qa_router.put("", response_model=QuestionAnswerOut)
async def upsert_question_answer(
    payload: QuestionAnswerIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> QuestionAnswer:
    h = _hash_question(payload.question_text)
    existing = (
        await db.execute(
            select(QuestionAnswer).where(
                QuestionAnswer.user_id == user.id,
                QuestionAnswer.question_hash == h,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = QuestionAnswer(
            user_id=user.id,
            question_hash=h,
            question_text=payload.question_text[:2000],
            answer=payload.answer,
            source=(payload.source or "manual")[:32],
        )
        db.add(existing)
    else:
        existing.question_text = payload.question_text[:2000]
        existing.answer = payload.answer
        if payload.source:
            existing.source = payload.source[:32]
    await db.commit()
    await db.refresh(existing)
    return existing


@qa_router.delete("/{qa_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question_answer(
    qa_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = (
        await db.execute(
            select(QuestionAnswer).where(
                QuestionAnswer.id == qa_id,
                QuestionAnswer.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Question not found")
    await db.delete(row)
    await db.commit()


# A list of (question_text, profile_lookup_callable) pairs used to seed the
# question bank from the user's existing profile. Each callable receives the
# loaded ResumeProfile / WorkAuthorization / Demographics rows and returns
# the answer string (or None to skip).
def _seed_pairs():
    return [
        ("What is your full name?",
         lambda rp, _wa, _dm: rp.full_name if rp else None),
        ("What is your email address?",
         lambda rp, _wa, _dm: rp.email if rp else None),
        ("What is your phone number?",
         lambda rp, _wa, _dm: rp.phone if rp else None),
        ("What is your current location?",
         lambda rp, _wa, _dm: rp.location if rp else None),
        ("What is your LinkedIn URL?",
         lambda rp, _wa, _dm: rp.linkedin_url if rp else None),
        ("What is your GitHub URL?",
         lambda rp, _wa, _dm: rp.github_url if rp else None),
        ("What is your portfolio URL?",
         lambda rp, _wa, _dm: rp.portfolio_url if rp else None),
        ("Are you legally authorized to work in the United States?",
         lambda _rp, wa, _dm: (
             "Yes" if wa and wa.work_authorization_status
             and "citizen" in (wa.work_authorization_status or "").lower()
             else None
         )),
        ("Will you now or in the future require visa sponsorship?",
         lambda _rp, wa, _dm: (
             "Yes" if wa and (wa.visa_sponsorship_required_now
                              or wa.visa_sponsorship_required_future)
             else "No" if wa else None
         )),
        ("What pronouns do you use?",
         lambda _rp, _wa, dm: dm.pronouns if dm and dm.pronouns else None),
    ]


@qa_router.post("/seed-from-profile")
async def seed_from_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Pre-populate the question bank from the user's profile so the
    auto-apply agent doesn't ask "what's your email" on the first
    application. Idempotent — only inserts a Q→A row when the hash
    isn't already present (so the user's manual edits are never
    overwritten)."""
    from app.models.preferences import (
        Demographics,
        ResumeProfile,
        WorkAuthorization,
    )

    rp = (await db.execute(
        select(ResumeProfile).where(ResumeProfile.user_id == user.id)
    )).scalar_one_or_none()
    wa = (await db.execute(
        select(WorkAuthorization).where(WorkAuthorization.user_id == user.id)
    )).scalar_one_or_none()
    dm = (await db.execute(
        select(Demographics).where(Demographics.user_id == user.id)
    )).scalar_one_or_none()

    inserted = 0
    skipped = 0
    for question, fn in _seed_pairs():
        try:
            answer = fn(rp, wa, dm)
        except Exception:
            answer = None
        if not answer:
            skipped += 1
            continue
        h = _hash_question(question)
        existing = (
            await db.execute(
                select(QuestionAnswer).where(
                    QuestionAnswer.user_id == user.id,
                    QuestionAnswer.question_hash == h,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue
        db.add(
            QuestionAnswer(
                user_id=user.id,
                question_hash=h,
                question_text=question[:2000],
                answer=str(answer)[:8000],
                source="profile_seed",
            )
        )
        inserted += 1
    await db.commit()
    return {"inserted": inserted, "skipped": skipped}


def register(app) -> None:
    app.include_router(router, prefix="/api/v1")
    app.include_router(runs_router, prefix="/api/v1")
    app.include_router(qa_router, prefix="/api/v1")
