"""Prompt editing + A/B experiment API (Settings → Prompts).

GET  /prompts                 — every agent action's prompt, with flags
GET  /prompts/{key}           — default + custom variants, weights, shares
PUT  /prompts/{key}           — replace the variant list
DELETE /prompts/{key}/variants/{id} — permanently delete one variant
POST /prompts/{key}/preview   — render a template against sample values
GET  /prompts/{key}/stats     — per-variant outcomes for document prompts
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.documents import GeneratedDocument
from app.models.jobs import TrackedJob
from app.models.user import User
from app.skills import prompt_registry as reg

router = APIRouter(prefix="/prompts", tags=["prompts"])

# Outcome ladders for the scoreboard. Statuses are the job's CURRENT
# status, so a job counts at the furthest stage it has reached.
APPLIED_PLUS = {
    "applied", "responded", "screening", "interviewing", "assessment",
    "offer", "won", "lost", "ghosted", "withdrawn",
}
RESPONDED = {"responded", "screening", "interviewing", "assessment", "offer", "won"}
INTERVIEWED = {"interviewing", "assessment", "offer", "won"}
OFFERED = {"offer", "won"}


def _require(key: str) -> None:
    if key not in reg.BY_KEY:
        raise HTTPException(status_code=404, detail=f"Unknown prompt '{key}'")


@router.get("")
async def list_prompts(_: User = Depends(get_current_user)) -> dict:
    return {"prompts": reg.list_prompts()}


@router.get("/{key}")
async def get_prompt(key: str, _: User = Depends(get_current_user)) -> dict:
    _require(key)
    return reg.get_prompt(key)


class VariantIn(BaseModel):
    id: Optional[str] = None
    name: str = Field(default="variant", max_length=80)
    template: Optional[str] = None  # ignored for the built-in default
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0, le=100)


class PromptSaveIn(BaseModel):
    variants: list[VariantIn]


@router.put("/{key}")
async def save_prompt(
    key: str, payload: PromptSaveIn, _: User = Depends(get_current_user)
) -> dict:
    _require(key)
    try:
        return reg.save_prompt(key, [v.model_dump() for v in payload.variants])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/{key}/variants/{variant_id}")
async def delete_variant(
    key: str, variant_id: str, _: User = Depends(get_current_user)
) -> dict:
    """Permanently delete one custom variant (frees its slot)."""
    _require(key)
    try:
        return reg.delete_variant(key, variant_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"No variant '{variant_id}' on prompt '{key}'")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class PreviewIn(BaseModel):
    template: str = Field(max_length=reg.MAX_TEMPLATE_CHARS)


@router.post("/{key}/preview")
async def preview_prompt(
    key: str, payload: PreviewIn, _: User = Depends(get_current_user)
) -> dict:
    """Render with each placeholder shown as «name», and flag placeholders
    the built-in default uses that this template dropped (usually a
    mistake — e.g. no {job_description} in a tailor prompt) or names
    the code never supplies (they'll stay literal)."""
    _require(key)
    known = reg.placeholders(reg.default_template(key))
    used = reg.placeholders(payload.template)
    return {
        "rendered": reg.render_template(
            payload.template, {k: f"«{k}»" for k in known}
        ),
        "missing_placeholders": [k for k in known if k not in used],
        "unknown_placeholders": [k for k in used if k not in known],
    }


@router.get("/{key}/stats")
async def prompt_stats(
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Per-variant scoreboard. Each job is attributed to the variant of
    its MOST RECENT document from this prompt (the one the Apply button
    downloads), so a job that had A then B regenerated counts for B
    only. Rates use jobs that reached `applied` or later as the
    denominator."""
    _require(key)
    rows = (
        await db.execute(
            select(
                GeneratedDocument.tracked_job_id,
                GeneratedDocument.prompt_variant,
                GeneratedDocument.created_at,
            ).where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.deleted_at.is_(None),
                GeneratedDocument.prompt_variant.like(f"{key}:%"),
            )
        )
    ).all()

    docs_by_variant: dict[str, int] = {}
    latest: dict[int, tuple] = {}
    for job_id, pv, created in rows:
        vid = pv.split(":", 1)[1]
        docs_by_variant[vid] = docs_by_variant.get(vid, 0) + 1
        if job_id is not None and (job_id not in latest or created > latest[job_id][1]):
            latest[job_id] = (vid, created)

    statuses: dict[int, str] = {}
    if latest:
        for jid, st in (
            await db.execute(
                select(TrackedJob.id, TrackedJob.status).where(
                    TrackedJob.id.in_(list(latest)),
                    TrackedJob.user_id == user.id,
                    TrackedJob.deleted_at.is_(None),
                )
            )
        ).all():
            statuses[jid] = st

    names = {v["id"]: v["name"] for v in reg.get_prompt(key)["variants"]}
    agg: dict[str, dict] = {}
    for jid, (vid, _) in latest.items():
        st = statuses.get(jid)
        if st is None:
            continue
        a = agg.setdefault(vid, {"jobs": 0, "applied": 0, "responded": 0,
                                 "interviewed": 0, "offered": 0})
        a["jobs"] += 1
        a["applied"] += st in APPLIED_PLUS
        a["responded"] += st in RESPONDED
        a["interviewed"] += st in INTERVIEWED
        a["offered"] += st in OFFERED

    def rate(n: int, d: int) -> Optional[float]:
        return round(n / d, 3) if d else None

    out = []
    for vid in sorted(set(docs_by_variant) | set(agg), key=lambda v: (v != reg.DEFAULT_ID, v)):
        a = agg.get(vid, {"jobs": 0, "applied": 0, "responded": 0,
                          "interviewed": 0, "offered": 0})
        out.append({
            "variant_id": vid,
            "name": names.get(vid, f"(deleted variant {vid})"),
            "documents": docs_by_variant.get(vid, 0),
            **a,
            "response_rate": rate(a["responded"], a["applied"]),
            "interview_rate": rate(a["interviewed"], a["applied"]),
            "offer_rate": rate(a["offered"], a["applied"]),
            "small_sample": a["applied"] < 20,
        })
    return {"key": key, "variants": out}
