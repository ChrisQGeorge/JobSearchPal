"""The Tower — the job-search incremental game (logic: app/skills/game.py).

GET  /game                      — balances, SV (ticked), floors, bonuses, cosmetics, memo feed
POST /game/floors/{id}/buy      — expand a department (scrip / chits)
POST /game/bonuses/{id}/buy     — Executive Bonus (SV); "dept:<floor>" for a Departmental Bonus
POST /game/cosmetics/{id}/buy   — cosmetic (clout / handshakes)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.skills import game as g  # importing registers the award hook

router = APIRouter(prefix="/game", tags=["game"])


@router.get("")
async def get_game(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    out = await g.view(db, user.id)
    await db.commit()
    return out


async def _buy(db: AsyncSession, user: User, fn, item_id: str) -> dict:
    try:
        await fn(db, user.id, item_id)
    except g.GameError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    out = await g.view(db, user.id)
    await db.commit()
    return out


@router.post("/floors/{floor_id}/buy")
async def buy_floor(
    floor_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await _buy(db, user, g.buy_floor, floor_id)


@router.post("/bonuses/{bonus_id}/buy")
async def buy_bonus(
    bonus_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await _buy(db, user, g.buy_bonus, bonus_id)


@router.post("/cosmetics/{item_id}/buy")
async def buy_cosmetic(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return await _buy(db, user, g.buy_cosmetic, item_id)
