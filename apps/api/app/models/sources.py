"""Job sources (registered ATS feeds) and job leads (postings pulled
from those feeds, awaiting user triage)."""
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class JobSource(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """A registered ATS feed the user wants polled.

    `kind` selects the adapter (greenhouse / lever / ashby / workable /
    rss / yc). `slug_or_url` is the per-kind identifier — for ATSes it's
    the company slug ("airbnb" for greenhouse), for RSS / YC it's the
    full feed URL. `filters` is a JSON blob with optional title regex,
    location regex, and remote-only filtering applied at ingest time so
    we don't pile in irrelevant rows."""

    __tablename__ = "job_sources"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    slug_or_url: Mapped[str] = mapped_column(String(512), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    filters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    poll_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    lead_ttl_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=168)
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_lead_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class JobLead(Base, IdMixin, TimestampMixin):
    """A single posting fetched from a JobSource. Lifecycle:

      new → user triages → interested / watching / dismissed
        interested or watching → "promoted" (tracked_jobs row created,
                                  fetch + score queued automatically)
        new (untouched) past expires_at → expired (filtered out by UI)

    Dedup key is `(source_id, external_id)` so re-polling never produces
    duplicates."""

    __tablename__ = "job_leads"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="ix_job_leads_source_external"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("job_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    organization_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    remote_policy: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    description_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="new", index=True)
    tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True
    )
    relevance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
