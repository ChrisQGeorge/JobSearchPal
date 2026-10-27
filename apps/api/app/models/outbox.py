"""Sol outbox — approved jobs published to a private GitHub repo for the
Sol application agent, with Sol's status records read back
(contract: docs/sol-outbox-contract.md; logic: app/skills/outbox.py)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class OutboxConfig(Base):
    """Per-user outbox settings + sync state. The GitHub token itself is an
    ApiCredential (provider "github_outbox"), never stored here.

    config: repo ("owner/name"), login, auto_approve, author_name,
            author_email, applicant (dict for applicant.json)
    state:  last_status_sha, last_sync_at, last_report (dict)"""

    __tablename__ = "outbox_config"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OutboxJob(Base, IdMixin):
    """One approved job in the outbox. `job_ref` ("jsp<id>") is the stable
    id written to job.json; tracked_job_id goes NULL if the job is deleted,
    so the folder can still be marked withdrawn."""

    __tablename__ = "outbox_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_ref", name="uq_outbox_job_ref"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set once the folder is on origin/main; `published_files` maps each
    # file name to the hash of its SOURCE (doc text / job.json), so a
    # regenerated document is detected without re-rendering PDFs.
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_files: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    withdraw_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    withdrawn_published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Sol's record from the `status` branch (untrusted text, capped).
    sol_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sol_status_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    sol_confirmation: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sol_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
