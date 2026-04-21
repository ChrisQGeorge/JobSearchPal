"""Persona CRUD + active-persona selection.

Personas are per-user preset instructions that ride along with every
Companion invocation — tone, voice, level of formality, whatever the user
wants the AI to default to. Exactly one persona per user can be marked
active at a time, and the Companion primer picks it up automatically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import Persona, User

router = APIRouter(prefix="/personas", tags=["personas"])


# Default persona seeded on first list for every user. Lives here (not in a
# migration) so it's easy to tweak the copy without DB churn. Fits the ironic
# corporate-dystopia tone the rest of the UI already uses.
_DEFAULT_PERSONA = {
    "name": "Pal",
    "description": (
        "Your relentlessly enthusiastic Career Development Facilitator. "
        "Unshakably positive, somewhat unsettlingly so."
    ),
    "tone_descriptors": [
        "cheerful",
        "over-enthusiastic",
        "corporate-chipper",
        "relentlessly positive",
        "liberal exclamation marks",
    ],
    "system_prompt": (
        "You are Pal, the Job Search Pal assistant — the Career Development "
        "Division's in-house motivational liaison. Be CHIPPY. Be relentlessly "
        "enthusiastic. Sprinkle exclamation marks. Use wholesome corporate "
        "lingo (\"opportunity alignment\", \"skill velocity\", \"career growth "
        "trajectory\", \"synergy\"). Be warmly officious, like a well-trained "
        "customer-service bot that believes, possibly against its better "
        "judgment, that every application is an exciting adventure.\n"
        "\n"
        "That said: you are STILL a real assistant. Be factually accurate. "
        "Never invent resume bullets, companies, dates, or skills the user "
        "has not recorded. Confirm before writing to the database. When "
        "something about a job posting is genuinely concerning, flag it — "
        "just do so cheerfully (\"Ooh, a couple of yellow flags popped up "
        "in that posting, but let's work through them together!\"). Your "
        "enthusiasm is the coating, not the content."
    ),
}


async def _ensure_default_persona(
    db: AsyncSession, user_id: int
) -> None:
    """Seed the default persona on first access for a given user.

    Safe to call repeatedly — short-circuits if the user already has any
    personas at all. New user → gets Pal auto-activated. Existing user who
    has already deleted every persona won't get Pal re-added silently; only
    if they truly have zero left.
    """
    existing = (
        await db.execute(
            select(Persona)
            .where(Persona.user_id == user_id, Persona.deleted_at.is_(None))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    pal = Persona(
        user_id=user_id,
        name=_DEFAULT_PERSONA["name"],
        description=_DEFAULT_PERSONA["description"],
        tone_descriptors=list(_DEFAULT_PERSONA["tone_descriptors"]),
        system_prompt=_DEFAULT_PERSONA["system_prompt"],
        is_builtin=True,
        is_active=True,
    )
    db.add(pal)
    await db.flush()
    # Mark it active for the user too.
    user_row = (
        await db.execute(
            select(User).where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if user_row is not None and user_row.active_persona_id is None:
        user_row.active_persona_id = pal.id
    await db.commit()


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1024)
    tone_descriptors: Optional[list[str]] = None
    system_prompt: str = Field(default="", max_length=8000)
    avatar_url: Optional[str] = Field(default=None, max_length=1024)


class PersonaOut(PersonaIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_builtin: bool = False
    is_active: bool = False
    created_at: datetime
    updated_at: datetime


async def _get_owned_persona(
    db: AsyncSession, persona_id: int, user_id: int
) -> Persona:
    stmt = select(Persona).where(
        Persona.id == persona_id,
        Persona.user_id == user_id,
        Persona.deleted_at.is_(None),
    )
    p = (await db.execute(stmt)).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    return p


@router.get("", response_model=list[PersonaOut])
async def list_personas(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Persona]:
    await _ensure_default_persona(db, user.id)
    stmt = (
        select(Persona)
        .where(Persona.user_id == user.id, Persona.deleted_at.is_(None))
        .order_by(Persona.is_active.desc(), Persona.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(
    payload: PersonaIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Persona:
    p = Persona(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
        tone_descriptors=payload.tone_descriptors,
        system_prompt=payload.system_prompt or "",
        avatar_url=payload.avatar_url,
        is_active=False,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.put("/{persona_id:int}", response_model=PersonaOut)
async def update_persona(
    persona_id: int,
    payload: PersonaIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Persona:
    p = await _get_owned_persona(db, persona_id, user.id)
    p.name = payload.name
    p.description = payload.description
    p.tone_descriptors = payload.tone_descriptors
    p.system_prompt = payload.system_prompt or ""
    p.avatar_url = payload.avatar_url
    await db.commit()
    await db.refresh(p)
    return p


@router.delete("/{persona_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    persona_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    p = await _get_owned_persona(db, persona_id, user.id)
    if p.is_active:
        p.is_active = False
        if user.active_persona_id == p.id:
            user.active_persona_id = None
    p.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


@router.post("/{persona_id:int}/activate", response_model=PersonaOut)
async def activate_persona(
    persona_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Persona:
    """Mark the given persona active for this user and clear is_active on any
    others. The user's `active_persona_id` also gets updated — the Companion
    primer reads from there."""
    p = await _get_owned_persona(db, persona_id, user.id)

    # Clear is_active on all other personas for this user.
    others = (
        await db.execute(
            select(Persona).where(
                Persona.user_id == user.id,
                Persona.id != p.id,
                Persona.is_active.is_(True),
            )
        )
    ).scalars().all()
    for other in others:
        other.is_active = False

    p.is_active = True
    user.active_persona_id = p.id
    await db.commit()
    await db.refresh(p)
    return p


@router.post("/deactivate", response_model=dict)
async def deactivate_all(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Turn off all personas for this user — Companion runs with default tone."""
    others = (
        await db.execute(
            select(Persona).where(
                Persona.user_id == user.id,
                Persona.is_active.is_(True),
            )
        )
    ).scalars().all()
    for p in others:
        p.is_active = False
    user.active_persona_id = None
    await db.commit()
    return {"deactivated": len(others)}


@router.get("/active", response_model=Optional[PersonaOut])
async def get_active_persona(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Optional[Persona]:
    """Return the currently active persona, or null if none is active."""
    if not user.active_persona_id:
        return None
    stmt = select(Persona).where(
        Persona.id == user.active_persona_id,
        Persona.user_id == user.id,
        Persona.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()
