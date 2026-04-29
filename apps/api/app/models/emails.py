"""ParsedEmail — every email run through the email-ingest classifier."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ParsedEmail(Base, IdMixin, TimestampMixin):
    """One parsed email. Lifecycle:

      new (Claude classified, awaiting user confirmation)
        → applied  (user confirmed and the suggested action ran)
        → dismissed (user rejected the suggestion)
        → errored  (Claude parse failed; user can retry)
    """

    __tablename__ = "parsed_emails"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_address: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    body_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Hash so re-pastes of the same email don't double-up.
    dedupe_hash: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    classification: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="new", index=True)
    applied_event_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("application_events.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
