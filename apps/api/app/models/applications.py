"""Application-run + question-bank models (R10)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ApplicationRun(Base, IdMixin, TimestampMixin):
    """One Companion-driven attempt to apply to a tracked job. State
    machine: queued → running → (awaiting_user ↔ running)* →
    submitted | failed | cancelled. The matching `apply_run` queue
    row's id lives in `queue_id` so the activity feed can correlate."""

    __tablename__ = "application_run"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracked_job_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tracked_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="generic")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    ats_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    queue_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    transcript_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    screenshot_dir: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pending_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pending_question_hash: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class ApplicationRunStep(Base, IdMixin):
    """Append-only event log per ApplicationRun. The /applications page
    replays this to show what the agent actually did. `kind` is one of:
    navigate / click / type / screenshot / dom_read / ask_user /
    answer / submit / error / note."""

    __tablename__ = "application_run_step"

    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("application_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    screenshot_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)


class QuestionAnswer(Base, IdMixin, TimestampMixin):
    """Per-user question bank. SHA-1 of the normalized question text →
    user's stored answer. The Companion reads from here on every form
    field; novel questions trigger an ask_user pause and write back here
    once answered."""

    __tablename__ = "question_answer"
    __table_args__ = (
        UniqueConstraint("user_id", "question_hash", name="uq_question_answer_user_hash"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_hash: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AutoApplySettings(Base, IdMixin, TimestampMixin):
    """Per-user policy for the auto-apply background poller.

    The poller wakes every few minutes, scans every user with
    `enabled=True`, and enqueues `apply_run` rows for the highest-fit
    `interested` tracked jobs that haven't been applied to yet —
    bounded by `daily_cap` per UTC day. `min_fit_score` (when set)
    gates lower-quality matches so the auto-pilot doesn't burn through
    Claude budget on bad-fit positions. `only_known_ats` further
    narrows to URLs whose ATS the apply_run handler knows how to drive
    (greenhouse / lever / ashby / workable) until the generic loop is
    proven."""

    __tablename__ = "auto_apply_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_auto_apply_settings_user"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    daily_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    min_fit_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    only_known_ats: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pause_start_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pause_end_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Bumped by the web /browser page's heartbeat while the tab is
    # visible. The auto-apply poller refuses to spawn runs when this
    # value is older than the configured grace window, so the agent
    # only fires when the user has eyes on the streamed browser.
    last_browser_visible_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
