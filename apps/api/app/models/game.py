"""The Tower — the job-search incremental game (see app/skills/game.py)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class GameLedger(Base, IdMixin):
    """Every earn (+) and spend (−) of the four earned currencies: scrip,
    chits, clout, handshakes. Balances are SUM(amount) per currency.
    Earn rows carry the job and are unique per (user, reason, job) — each
    job pays each kind of award once. Spend rows have job_id NULL."""

    __tablename__ = "game_ledger"
    __table_args__ = (
        UniqueConstraint("user_id", "reason", "job_id", name="uq_game_ledger_award"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GameState(Base):
    """Per-user game state: Shareholder Value, floor levels, bonuses,
    cosmetics, last accrual tick (JSON — the shape lives in skills/game.py)."""

    __tablename__ = "game_state"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
