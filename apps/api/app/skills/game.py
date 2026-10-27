"""The Tower — a job-search incremental game.

Currencies
  scrip       Submission Scrip — +1 award per job that reaches "applied"
              (or any later stage) for the first time.
  chits       Diligence Chits — +1 award per job taken out of "to_review".
  clout       Networking Clout — a job reaching an interview stage
              (screening / interviewing / assessment). Cosmetics only.
  handshakes  Golden Handshakes — a job reaching offer / won. Cosmetics only.
  SV          Shareholder Value — the main currency. NEVER earned directly:
              only produced (idle) by tower floors, which are bought with
              scrip + chits. SV buys Executive Bonuses (permanent, each
              level exponentially pricier) — some multiply SV, some make
              applying / reviewing pay MORE scrip / chits, so real job-search
              work always stays valuable.

Awards are recorded by a before_flush hook on every TrackedJob status
change (UI, bulk edits, MCP agents, email automation alike). Only real
transitions count — jobs created already "applied" (imports) pay nothing,
and nothing is back-paid. Each (job, award kind) pays once.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import event, func, select
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# --- Catalogue ----------------------------------------------------------------

BASE_SCRIP_PER_APPLICATION = 10
BASE_CHITS_PER_REVIEW = 2
CLOUT_PER_INTERVIEW = 1
HANDSHAKES_PER_OFFER = 1

APPLIED_PLUS = {"applied", "responded", "screening", "interviewing", "assessment", "offer", "won"}
INTERVIEW_STAGES = {"screening", "interviewing", "assessment"}
OFFER_STAGES = {"offer", "won"}

# Floors, bottom to top. cost: base price per currency for the FIRST level;
# each level multiplies by growth. svh: SV per hour per level.
FLOORS: list[dict[str, Any]] = [
    {
        "id": "mailroom", "name": "The Mailroom", "theme": "basement",
        "tagline": "Sub-basement 3. Sorting your applications into the void since forever.",
        "cost": {"scrip": 10}, "growth": 1.28, "svh": 6, "unlock": 0,
    },
    {
        "id": "compliance", "name": "Compliance & Review Board", "theme": "bureau",
        "tagline": "Every chit is triple-stamped, then filed under 'Pending Further Review'.",
        "cost": {"chits": 4}, "growth": 1.22, "svh": 3, "unlock": 0,
    },
    {
        "id": "synergy", "name": "Synergy Laboratory", "theme": "neon",
        "tagline": "Where scrip and chits are fused into pure, unregulated synergy.",
        "cost": {"scrip": 30, "chits": 20}, "growth": 1.32, "svh": 45, "unlock": 300,
    },
    {
        "id": "servers", "name": "The Server Farm", "theme": "crt",
        "tagline": "Ten thousand machines computing your Employee Value Score. It is low.",
        "cost": {"chits": 120}, "growth": 1.30, "svh": 90, "unlock": 3_000,
    },
    {
        "id": "hr", "name": "Human Resources (Resources)", "theme": "pastel",
        "tagline": "Humans, as a resource. Please enjoy the complimentary wellness pamphlet.",
        "cost": {"scrip": 120}, "growth": 1.33, "svh": 240, "unlock": 15_000,
    },
    {
        "id": "boardroom", "name": "The Boardroom", "theme": "mahogany",
        "tagline": "Decisions are made here. Not by you. But here.",
        "cost": {"scrip": 300, "chits": 600}, "growth": 1.38, "svh": 1_200, "unlock": 100_000,
    },
    {
        "id": "penthouse", "name": "Executive Penthouse", "theme": "gold",
        "tagline": "The view is lovely. The windows do not open.",
        "cost": {"scrip": 1_000, "chits": 3_000}, "growth": 1.45, "svh": 8_000, "unlock": 1_000_000,
    },
]
FLOOR_BY_ID = {f["id"]: f for f in FLOORS}

# Executive Bonuses — bought with SV; cost = base * mult^level.
BONUSES: list[dict[str, Any]] = [
    {
        "id": "performance", "name": "Performance Bonus",
        "desc": "+10% Shareholder Value from every floor, per level.",
        "base": 150, "mult": 2.4,
    },
    {
        "id": "efficiency", "name": "Efficiency Bonus",
        "desc": "Floors cost 5% less scrip & chits, per level (compounding).",
        "base": 300, "mult": 2.6,
    },
    {
        "id": "application_incentive", "name": "Application Incentive",
        "desc": "+3 Submission Scrip for every job you apply to, per level.",
        "base": 250, "mult": 2.8,
    },
    {
        "id": "diligence_incentive", "name": "Diligence Incentive",
        "desc": "+1 Diligence Chit for every job you review, per level.",
        "base": 200, "mult": 2.6,
    },
]
BONUS_BY_ID = {b["id"]: b for b in BONUSES}
# Per-floor "Departmental Bonus": +25% that floor's output per level.
DEPT_BONUS_PCT = 0.25
DEPT_BONUS_MULT = 2.2

# Cosmetics — bought with clout / handshakes; drawn in the tower.
COSMETICS: list[dict[str, Any]] = [
    {"id": "poster", "name": "'HANG IN THERE (MANDATORY)' Poster", "price": {"clout": 1}, "floor": "mailroom"},
    {"id": "ficus", "name": "Ficus of Compulsory Joy", "price": {"clout": 2}, "floor": "compliance"},
    {"id": "cooler", "name": "Gossip-Free Water Cooler", "price": {"clout": 3}, "floor": "synergy"},
    {"id": "plaque", "name": "Employee of the Month Plaque (You, Forever)", "price": {"clout": 5}, "floor": "hr"},
    {"id": "stapler", "name": "The Golden Stapler", "price": {"handshakes": 1}, "floor": "boardroom"},
    {"id": "aquarium", "name": "Executive Aquarium (One Sad Fish)", "price": {"handshakes": 2}, "floor": "penthouse"},
    {"id": "helipad", "name": "Rooftop Helipad (No Helicopter)", "price": {"handshakes": 3}, "floor": "roof"},
]
COSMETIC_BY_ID = {c["id"]: c for c in COSMETICS}

TITLES = [
    (0, "Unpaid Intern"),
    (100, "Associate Synergist"),
    (1_000, "Senior Paper Shuffler"),
    (10_000, "Middle Manager"),
    (100_000, "Director of Vision"),
    (1_000_000, "VP of Shareholder Delight"),
    (10_000_000, "Chief Value Extraction Officer"),
]

EARNED = ("scrip", "chits", "clout", "handshakes")


# --- State helpers ----------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def new_state() -> dict[str, Any]:
    return {
        "sv": 0.0,
        "lifetime_sv": 0.0,
        "last_tick": _now().isoformat(),
        "floors": {},
        "bonuses": {},
        "dept_bonuses": {},
        "cosmetics": [],
    }


def _lvl(state: dict, group: str, key: str) -> int:
    return int((state.get(group) or {}).get(key, 0) or 0)


def floor_svh(state: dict, floor_id: str, level: Optional[int] = None) -> float:
    f = FLOOR_BY_ID[floor_id]
    lv = _lvl(state, "floors", floor_id) if level is None else level
    perf = 1 + 0.10 * _lvl(state, "bonuses", "performance")
    dept = 1 + DEPT_BONUS_PCT * _lvl(state, "dept_bonuses", floor_id)
    return f["svh"] * lv * perf * dept


def total_svh(state: dict) -> float:
    return sum(floor_svh(state, f["id"]) for f in FLOORS)


def floor_cost(state: dict, floor_id: str) -> dict[str, int]:
    f = FLOOR_BY_ID[floor_id]
    lv = _lvl(state, "floors", floor_id)
    eff = max(0.3, 0.95 ** _lvl(state, "bonuses", "efficiency"))
    return {cur: int(math.ceil(base * (f["growth"] ** lv) * eff)) for cur, base in f["cost"].items()}


def bonus_cost(state: dict, bonus_id: str) -> int:
    b = BONUS_BY_ID[bonus_id]
    return int(math.ceil(b["base"] * (b["mult"] ** _lvl(state, "bonuses", bonus_id))))


def dept_bonus_cost(state: dict, floor_id: str) -> int:
    base = max(100, FLOOR_BY_ID[floor_id]["unlock"] // 2)
    return int(math.ceil(base * (DEPT_BONUS_MULT ** _lvl(state, "dept_bonuses", floor_id))))


def scrip_per_application(state: Optional[dict]) -> int:
    return BASE_SCRIP_PER_APPLICATION + 3 * _lvl(state or {}, "bonuses", "application_incentive")


def chits_per_review(state: Optional[dict]) -> int:
    return BASE_CHITS_PER_REVIEW + _lvl(state or {}, "bonuses", "diligence_incentive")


def title_for(lifetime_sv: float) -> tuple[str, Optional[tuple[int, str]]]:
    current, nxt = TITLES[0][1], None
    for i, (threshold, name) in enumerate(TITLES):
        if lifetime_sv >= threshold:
            current = name
            nxt = TITLES[i + 1] if i + 1 < len(TITLES) else None
    return current, nxt


def tick(state: dict, now: Optional[datetime] = None) -> dict:
    """Accrue idle SV since the last tick (server-side, so offline
    progress counts and nothing is trusted from the browser)."""
    now = now or _now()
    try:
        last = datetime.fromisoformat(state.get("last_tick") or now.isoformat())
    except ValueError:
        last = now
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - last).total_seconds() / 3600.0)
    gained = total_svh(state) * hours
    state["sv"] = float(state.get("sv") or 0.0) + gained
    state["lifetime_sv"] = float(state.get("lifetime_sv") or 0.0) + gained
    state["last_tick"] = now.isoformat()
    return state


# --- Awards (before_flush hook) ---------------------------------------------------

def _awards_for(prior: Optional[str], new: str) -> list[tuple[str, str]]:
    """(reason, currency) earned by one status transition."""
    out: list[tuple[str, str]] = []
    if prior is None or prior == new:
        return out
    if prior == "to_review" and new not in ("to_review", "archived"):
        out.append(("review", "chits"))
    if new in APPLIED_PLUS and prior not in APPLIED_PLUS:
        out.append(("application", "scrip"))
    if new in INTERVIEW_STAGES:
        out.append(("interview", "clout"))
    if new in OFFER_STAGES:
        out.append(("offer", "handshakes"))
    return out


def _record_awards(session: Session) -> None:
    from app.models.game import GameLedger, GameState
    from app.models.jobs import TrackedJob

    pending: list[tuple[Any, str, str]] = []
    for obj in list(session.dirty):
        if not isinstance(obj, TrackedJob):
            continue
        hist = sa_inspect(obj).attrs.status.history
        if not hist.added or not hist.deleted:
            continue
        for reason, currency in _awards_for(hist.deleted[0], hist.added[0]):
            pending.append((obj, reason, currency))
    if not pending:
        return
    states: dict[int, Optional[dict]] = {}
    with session.no_autoflush:
        for job, reason, currency in pending:
            uid = job.user_id
            exists = session.execute(
                select(GameLedger.id).where(
                    GameLedger.user_id == uid,
                    GameLedger.reason == reason,
                    GameLedger.job_id == job.id,
                )
            ).first()
            if exists is not None or any(
                isinstance(o, GameLedger) and o.user_id == uid and o.reason == reason and o.job_id == job.id
                for o in session.new
            ):
                continue
            if uid not in states:
                gs = session.get(GameState, uid)
                states[uid] = gs.state if gs is not None else None
            st = states[uid]
            amount = {
                "scrip": scrip_per_application(st),
                "chits": chits_per_review(st),
                "clout": CLOUT_PER_INTERVIEW,
                "handshakes": HANDSHAKES_PER_OFFER,
            }[currency]
            session.add(GameLedger(
                user_id=uid, currency=currency, amount=amount, reason=reason,
                job_id=job.id, note=(job.title or "")[:200],
            ))


@event.listens_for(Session, "before_flush")
def _game_before_flush(session: Session, _ctx, _instances) -> None:
    try:
        _record_awards(session)
    except Exception:  # noqa: BLE001 — the game must never block a job update
        log.exception("game: award recording failed (job update continues)")


# --- Reads / purchases -------------------------------------------------------------

async def balances(db, user_id: int) -> dict[str, int]:
    from app.models.game import GameLedger

    rows = (
        await db.execute(
            select(GameLedger.currency, func.coalesce(func.sum(GameLedger.amount), 0))
            .where(GameLedger.user_id == user_id)
            .group_by(GameLedger.currency)
        )
    ).all()
    out = {c: 0 for c in EARNED}
    out.update({c: int(n) for c, n in rows})
    return out


async def load_state(db, user_id: int, lock: bool = False):
    """(GameState row, ticked state dict). Creates the row on first visit."""
    from app.models.game import GameState

    stmt = select(GameState).where(GameState.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = GameState(user_id=user_id, state=new_state())
        db.add(row)
        await db.flush()
    state = tick(dict(row.state or new_state()))
    return row, state


def save_state(row, state: dict) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    row.state = dict(state)
    flag_modified(row, "state")


class GameError(ValueError):
    pass


async def _spend(db, user_id: int, price: dict[str, int], reason: str, have: dict[str, int]) -> None:
    from app.models.game import GameLedger

    short = {c: n - have.get(c, 0) for c, n in price.items() if have.get(c, 0) < n}
    if short:
        raise GameError(
            "Insufficient funds — short " + ", ".join(f"{n} {c}" for c, n in short.items()) + "."
        )
    for cur, n in price.items():
        db.add(GameLedger(user_id=user_id, currency=cur, amount=-int(n), reason=reason, job_id=None))


async def buy_floor(db, user_id: int, floor_id: str) -> None:
    if floor_id not in FLOOR_BY_ID:
        raise GameError("No such floor.")
    row, state = await load_state(db, user_id, lock=True)
    f = FLOOR_BY_ID[floor_id]
    if state["lifetime_sv"] < f["unlock"]:
        raise GameError(f"Under construction — unlocks at {f['unlock']:,} lifetime Shareholder Value.")
    await _spend(db, user_id, floor_cost(state, floor_id), f"floor:{floor_id}", await balances(db, user_id))
    state.setdefault("floors", {})[floor_id] = _lvl(state, "floors", floor_id) + 1
    save_state(row, state)


async def buy_bonus(db, user_id: int, bonus_id: str) -> None:
    row, state = await load_state(db, user_id, lock=True)
    if bonus_id.startswith("dept:"):
        floor_id = bonus_id.split(":", 1)[1]
        if floor_id not in FLOOR_BY_ID or _lvl(state, "floors", floor_id) < 1:
            raise GameError("Build that floor first.")
        cost, group, key = dept_bonus_cost(state, floor_id), "dept_bonuses", floor_id
    elif bonus_id in BONUS_BY_ID:
        cost, group, key = bonus_cost(state, bonus_id), "bonuses", bonus_id
    else:
        raise GameError("No such bonus.")
    if state["sv"] < cost:
        raise GameError(f"Insufficient Shareholder Value — need {cost:,}.")
    state["sv"] -= cost
    state.setdefault(group, {})[key] = _lvl(state, group, key) + 1
    save_state(row, state)


async def buy_cosmetic(db, user_id: int, item_id: str) -> None:
    item = COSMETIC_BY_ID.get(item_id)
    if item is None:
        raise GameError("No such item.")
    row, state = await load_state(db, user_id, lock=True)
    if item_id in (state.get("cosmetics") or []):
        raise GameError("Already owned.")
    await _spend(db, user_id, item["price"], f"cosmetic:{item_id}", await balances(db, user_id))
    state["cosmetics"] = list(state.get("cosmetics") or []) + [item_id]
    save_state(row, state)


async def view(db, user_id: int) -> dict[str, Any]:
    """Everything the Tower page renders."""
    from app.models.game import GameLedger

    row, state = await load_state(db, user_id)
    save_state(row, state)  # persist the tick
    have = await balances(db, user_id)
    title, nxt = title_for(state["lifetime_sv"])
    recent = (
        await db.execute(
            select(GameLedger)
            .where(GameLedger.user_id == user_id, GameLedger.amount > 0)
            .order_by(GameLedger.id.desc())
            .limit(12)
        )
    ).scalars().all()
    floors = []
    for f in FLOORS:
        lv = _lvl(state, "floors", f["id"])
        cost = floor_cost(state, f["id"])
        floors.append({
            "id": f["id"], "name": f["name"], "theme": f["theme"], "tagline": f["tagline"],
            "level": lv,
            "unlocked": state["lifetime_sv"] >= f["unlock"],
            "unlock_at": f["unlock"],
            "cost": cost,
            "affordable": all(have.get(c, 0) >= n for c, n in cost.items()),
            "svh": floor_svh(state, f["id"]),
            "next_gain_svh": floor_svh(state, f["id"], lv + 1) - floor_svh(state, f["id"]),
            "dept_bonus_level": _lvl(state, "dept_bonuses", f["id"]),
            "dept_bonus_cost": dept_bonus_cost(state, f["id"]),
        })
    return {
        "balances": have,
        "sv": state["sv"],
        "lifetime_sv": state["lifetime_sv"],
        "svh": total_svh(state),
        "title": title,
        "next_title": {"at": nxt[0], "name": nxt[1]} if nxt else None,
        "earn_rates": {
            "scrip_per_application": scrip_per_application(state),
            "chits_per_review": chits_per_review(state),
            "clout_per_interview": CLOUT_PER_INTERVIEW,
            "handshakes_per_offer": HANDSHAKES_PER_OFFER,
        },
        "floors": floors,
        "bonuses": [
            {
                "id": b["id"], "name": b["name"], "desc": b["desc"],
                "level": _lvl(state, "bonuses", b["id"]), "cost": bonus_cost(state, b["id"]),
            }
            for b in BONUSES
        ],
        "cosmetics": [
            {**c, "owned": c["id"] in (state.get("cosmetics") or [])} for c in COSMETICS
        ],
        "recent": [
            {"currency": r.currency, "amount": r.amount, "reason": r.reason, "note": r.note,
             "at": r.created_at.isoformat() if r.created_at else None}
            for r in recent
        ],
        "server_time": _now().isoformat(),
    }
