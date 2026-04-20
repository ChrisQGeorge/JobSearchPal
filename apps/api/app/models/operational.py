"""Audit log, autofill log, and metric snapshots."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.models.base import Base, IdMixin, TimestampMixin


class AuditLog(Base, IdMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    diff: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class AutofillLog(Base, IdMixin, TimestampMixin):
    __tablename__ = "autofill_logs"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fields_shared: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    recipient: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class MetricSnapshot(Base, IdMixin, TimestampMixin):
    __tablename__ = "metric_snapshots"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
