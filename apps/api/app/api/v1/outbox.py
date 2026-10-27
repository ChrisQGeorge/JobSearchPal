"""Sol outbox — hand approved jobs to the Sol agent through a private GitHub
repo and read back what it applied to (logic: app/skills/outbox.py).

GET    /outbox                          — connection, settings, last sync report
POST   /outbox/connect                  — {repo, token}: verify with GitHub, store encrypted
DELETE /outbox/connect                  — forget the token + local clone (repo untouched)
PUT    /outbox/settings                 — auto_approve, commit author, applicant.json answers
POST   /outbox/sync                     — sync now (background; poll GET /outbox)
GET    /outbox/jobs                     — everything in the outbox, newest first
GET    /outbox/jobs/{job_id}            — one job's outbox state + whether it can be sent
POST   /outbox/jobs/{job_id}/approve    — {notes?}: send this job to Sol
POST   /outbox/jobs/approve             — {job_ids}: bulk send
POST   /outbox/jobs/{job_id}/withdraw   — {reason?}: add withdrawn.json (nothing deleted)
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.v1.api_credentials import get_user_secret
from app.core.database import get_db, long_running
from app.core.deps import get_current_user
from app.core.security import encrypt_secret
from app.models.jobs import Organization, TrackedJob
from app.models.outbox import OutboxConfig, OutboxJob
from app.models.user import ApiCredential, User
from app.skills import outbox as ob

router = APIRouter(prefix="/outbox", tags=["outbox"])

GITHUB_API = "https://api.github.com"


async def _config_row(db: AsyncSession, user_id: int, create: bool = False) -> Optional[OutboxConfig]:
    row = await db.get(OutboxConfig, user_id)
    if row is None and create:
        row = OutboxConfig(user_id=user_id, config={}, state={})
        db.add(row)
        await db.flush()
    return row


async def _credential(db: AsyncSession, user_id: int) -> Optional[ApiCredential]:
    return (
        await db.execute(
            select(ApiCredential).where(
                ApiCredential.user_id == user_id,
                ApiCredential.provider == ob.PROVIDER,
                ApiCredential.label == "default",
            )
        )
    ).scalar_one_or_none()


async def _overview(db: AsyncSession, user_id: int) -> dict[str, Any]:
    row = await _config_row(db, user_id)
    cfg = dict(row.config) if row else {}
    state = dict(row.state) if row else {}
    cred = await _credential(db, user_id)
    connected = bool(cfg.get("repo")) and cred is not None and cred.deleted_at is None
    counts = {"total": 0, "published": 0, "pending": 0, "applied": 0, "skipped": 0, "closed": 0, "withdrawn": 0, "errors": 0}
    for o in (await db.execute(select(OutboxJob).where(OutboxJob.user_id == user_id))).scalars():
        counts["total"] += 1
        if o.withdrawn_at:
            counts["withdrawn"] += 1
        elif o.published_at:
            counts["published"] += 1
        else:
            counts["pending"] += 1
        if o.sol_status in ("applied", "skipped", "closed"):
            counts[o.sol_status] += 1
        if o.last_error:
            counts["errors"] += 1
    return {
        "connected": connected,
        "repo": cfg.get("repo"),
        "login": cfg.get("login") if connected else None,
        "repo_private": cfg.get("repo_private"),
        "connected_at": cfg.get("connected_at"),
        "auto_approve": bool(cfg.get("auto_approve")),
        "author_name": cfg.get("author_name") or "",
        "author_email": cfg.get("author_email") or "",
        "applicant": cfg.get("applicant") or {},
        "last_sync_at": state.get("last_sync_at"),
        "last_report": state.get("last_report"),
        "running": ob.is_running(user_id),
        "sync_seconds": ob.SYNC_SECONDS,
        "counts": counts,
    }


@router.get("")
async def get_outbox(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return await _overview(db, user.id)


class ConnectIn(BaseModel):
    repo: str = Field(min_length=3, max_length=201)
    token: str = Field(min_length=10, max_length=512)


def _gh_error(resp: httpx.Response, what: str) -> HTTPException:
    try:
        msg = resp.json().get("message") or ""
    except ValueError:
        msg = resp.text[:200]
    return HTTPException(status_code=400, detail=f"GitHub refused {what} (HTTP {resp.status_code}): {msg}")


@router.post("/connect")
@long_running
async def connect(payload: ConnectIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Verify the token can see the repo, then store it encrypted. The
    token is never returned, logged or written anywhere else."""
    repo = payload.repo.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if not ob.REPO_RE.match(repo):
        raise HTTPException(status_code=400, detail="Repo must look like owner/name (e.g. my-outbox-account/jobsearchpal-outbox).")
    token = payload.token.strip()
    await db.commit()  # don't hold a transaction across the GitHub calls
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            me = await client.get(f"{GITHUB_API}/user", headers=headers)
            if me.status_code != 200:
                raise _gh_error(me, "the token")
            rp = await client.get(f"{GITHUB_API}/repos/{repo}", headers=headers)
            if rp.status_code != 200:
                raise _gh_error(rp, f"access to {repo} (check the token's repository access)")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't reach GitHub: {type(exc).__name__}: {exc}")
    login = str(me.json().get("login") or "")[:100]
    repo_info = rp.json()
    perms = repo_info.get("permissions") or {}
    if perms and not perms.get("push"):
        raise HTTPException(
            status_code=400,
            detail=f"{login} can see {repo} but can't push to it — the token needs Contents: read and write.",
        )

    cred = await _credential(db, user.id)
    if cred is None:
        db.add(ApiCredential(user_id=user.id, provider=ob.PROVIDER, label="default", encrypted_secret=encrypt_secret(token)))
    else:
        cred.encrypted_secret = encrypt_secret(token)
        cred.deleted_at = None
    row = await _config_row(db, user.id, create=True)
    cfg = dict(row.config or {})
    if cfg.get("repo") != repo:
        row.state = {}  # new repo: forget the old status-branch SHA
        flag_modified(row, "state")
    cfg.update(
        repo=repo,
        login=login,
        repo_private=bool(repo_info.get("private")),
        connected_at=datetime.now(timezone.utc).isoformat(),
    )
    row.config = cfg
    flag_modified(row, "config")
    await db.commit()
    ob.kick(user.id)
    return await _overview(db, user.id)


@router.delete("/connect")
async def disconnect(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    cred = await _credential(db, user.id)
    if cred is not None:
        cred.deleted_at = datetime.now(timezone.utc)
        cred.encrypted_secret = encrypt_secret("")
    row = await _config_row(db, user.id)
    if row is not None:
        cfg = dict(row.config or {})
        cfg.pop("login", None)
        row.config = cfg
        flag_modified(row, "config")
    await db.commit()
    shutil.rmtree(ob.clone_dir(user.id), ignore_errors=True)
    return await _overview(db, user.id)


class SettingsIn(BaseModel):
    auto_approve: Optional[bool] = None
    author_name: Optional[str] = Field(default=None, max_length=100)
    author_email: Optional[str] = Field(default=None, max_length=200)
    applicant: Optional[dict] = None


@router.put("/settings")
async def save_settings(payload: SettingsIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = await _config_row(db, user.id, create=True)
    cfg = dict(row.config or {})
    if payload.auto_approve is not None:
        cfg["auto_approve"] = payload.auto_approve
    if payload.author_name is not None:
        cfg["author_name"] = payload.author_name.strip()
    if payload.author_email is not None:
        cfg["author_email"] = payload.author_email.strip()
    if payload.applicant is not None:
        # Keep only the contract's fields (build_applicant whitelists them).
        cfg["applicant"] = ob.build_applicant(payload.applicant) or {}
    row.config = cfg
    flag_modified(row, "config")
    await db.commit()
    if cfg.get("repo"):
        ob.kick(user.id)
    return await _overview(db, user.id)


@router.post("/sync")
async def sync_now(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    out = await _overview(db, user.id)
    if not out["connected"]:
        raise HTTPException(status_code=409, detail="Connect a GitHub repo first.")
    ob.kick(user.id)
    out["running"] = True
    return out


def _job_out(o: OutboxJob, title: Optional[str] = None, company: Optional[str] = None, status: Optional[str] = None) -> dict:
    return {
        "id": o.id,
        "job_id": o.tracked_job_id,
        "job_ref": o.job_ref,
        "slug": o.slug,
        "title": title,
        "company": company,
        "job_status": status,
        "notes": o.notes,
        "approved_at": o.approved_at,
        "published_at": o.published_at,
        "withdrawn_at": o.withdrawn_at,
        "withdraw_reason": o.withdraw_reason,
        "withdrawn_published_at": o.withdrawn_published_at,
        "sol_status": o.sol_status,
        "sol_status_at": o.sol_status_at,
        "sol_confirmation": o.sol_confirmation,
        "sol_note": o.sol_note,
        "last_error": o.last_error,
    }


@router.get("/jobs")
async def list_outbox_jobs(
    limit: int = 200, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = (
        await db.execute(
            select(OutboxJob, TrackedJob.title, Organization.name, TrackedJob.status)
            .outerjoin(TrackedJob, TrackedJob.id == OutboxJob.tracked_job_id)
            .outerjoin(Organization, Organization.id == TrackedJob.organization_id)
            .where(OutboxJob.user_id == user.id)
            .order_by(OutboxJob.approved_at.desc(), OutboxJob.id.desc())
            .limit(max(1, min(limit, 1000)))
        )
    ).all()
    return [_job_out(o, t, c, s) for o, t, c, s in rows]


async def _owned_job(db: AsyncSession, user_id: int, job_id: int) -> TrackedJob:
    job = await db.get(TrackedJob, job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


async def _job_state(db: AsyncSession, user_id: int, job: TrackedJob) -> dict:
    o = (
        await db.execute(select(OutboxJob).where(OutboxJob.user_id == user_id, OutboxJob.job_ref == ob.job_ref(job.id)))
    ).scalar_one_or_none()
    docs = await ob.latest_docs(db, user_id, [job.id])
    info = (await ob.apply_info(db, user_id, [job.id])).get(job.id)
    return {
        "connected": (await _overview(db, user_id))["connected"],
        "entry": _job_out(o) if o else None,
        "blocked_reason": ob.eligibility(job, (job.id, "resume") in docs, info),
        "apply_url": (info or {}).get("apply_link") if ob.is_linkedin(job) else ob._https(job.source_url),
        "has_cover_letter": (job.id, "cover_letter") in docs,
        "running": ob.is_running(user_id),
    }


@router.get("/jobs/{job_id:int}")
async def get_outbox_job(job_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return await _job_state(db, user.id, await _owned_job(db, user.id, job_id))


class ApproveIn(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=4000)


async def _approve_one(db: AsyncSession, user_id: int, job: TrackedJob, notes: Optional[str]) -> None:
    docs = await ob.latest_docs(db, user_id, [job.id])
    info = (await ob.apply_info(db, user_id, [job.id])).get(job.id)
    why = ob.eligibility(job, (job.id, "resume") in docs, info)
    if why:
        raise HTTPException(status_code=409, detail=why)
    existing = (
        await db.execute(select(OutboxJob).where(OutboxJob.user_id == user_id, OutboxJob.job_ref == ob.job_ref(job.id)))
    ).scalar_one_or_none()
    if existing is not None and existing.withdrawn_at is not None:
        raise HTTPException(
            status_code=409,
            detail="This job was withdrawn from the outbox — its folder has withdrawn.json, which Sol honours for good.",
        )
    await ob.approve(db, user_id, job, notes)


@router.post("/jobs/{job_id:int}/approve")
async def approve_job(
    job_id: int, payload: ApproveIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    if not (await _overview(db, user.id))["connected"]:
        raise HTTPException(status_code=409, detail="Connect the Sol outbox repo in Settings → Sol Outbox first.")
    job = await _owned_job(db, user.id, job_id)
    await _approve_one(db, user.id, job, payload.notes)
    await db.commit()
    ob.kick(user.id)
    out = await _job_state(db, user.id, job)
    out["running"] = True
    return out


class BulkApproveIn(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/jobs/approve")
async def approve_bulk(
    payload: BulkApproveIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    if not (await _overview(db, user.id))["connected"]:
        raise HTTPException(status_code=409, detail="Connect the Sol outbox repo in Settings → Sol Outbox first.")
    sent, skipped = [], []
    for jid in dict.fromkeys(payload.job_ids):
        job = await db.get(TrackedJob, jid)
        if job is None or job.user_id != user.id:
            skipped.append({"job_id": jid, "reason": "not found"})
            continue
        try:
            await _approve_one(db, user.id, job, None)
            sent.append(jid)
        except HTTPException as exc:
            skipped.append({"job_id": jid, "title": job.title, "reason": exc.detail})
    await db.commit()
    if sent:
        ob.kick(user.id)
    return {"sent": sent, "skipped": skipped}


class WithdrawIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/jobs/{job_id:int}/withdraw")
async def withdraw_job(
    job_id: int, payload: WithdrawIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    job = await _owned_job(db, user.id, job_id)
    o = (
        await db.execute(select(OutboxJob).where(OutboxJob.user_id == user.id, OutboxJob.job_ref == ob.job_ref(job.id)))
    ).scalar_one_or_none()
    if o is None:
        raise HTTPException(status_code=404, detail="This job isn't in the outbox.")
    if o.sol_status:
        raise HTTPException(status_code=409, detail=f"Sol already reported this job as {o.sol_status}.")
    if o.withdrawn_at is None:
        o.withdrawn_at = datetime.now(timezone.utc)
        o.withdraw_reason = (payload.reason or "").strip() or None
    await db.commit()
    ob.kick(user.id)
    return await _job_state(db, user.id, job)
