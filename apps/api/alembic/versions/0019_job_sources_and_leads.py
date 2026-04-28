"""job_sources + job_leads — registered ATS feeds and the unreviewed
postings they pull in.

A `JobSource` is a user-registered feed (Greenhouse / Lever / Ashby /
Workable / RSS / YC). Each source is polled by the background worker on
a per-source cadence (poll_interval_hours). A `JobLead` is a single
posting fetched from a source that the user hasn't acted on yet — they
expire after `lead_ttl_hours` if untouched. Acting on a lead promotes
it into a real `tracked_jobs` row.

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-28

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SOURCES_TABLE = "job_sources"
_LEADS_TABLE = "job_leads"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return insp.has_table(name)


def upgrade() -> None:
    if not _has_table(_SOURCES_TABLE):
        op.create_table(
            _SOURCES_TABLE,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("kind", sa.String(length=32), nullable=False, index=True),
            sa.Column("slug_or_url", sa.String(length=512), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("filters", sa.JSON(), nullable=True),
            sa.Column(
                "poll_interval_hours",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("24"),
            ),
            sa.Column(
                "lead_ttl_hours",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("168"),
            ),
            sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_lead_count", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_table(_LEADS_TABLE):
        op.create_table(
            _LEADS_TABLE,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "source_id",
                sa.BigInteger(),
                sa.ForeignKey("job_sources.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            # Stable identifier from the upstream feed so we can dedupe on
            # repeated polls (e.g. Greenhouse posting id).
            sa.Column("external_id", sa.String(length=255), nullable=False, index=True),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("organization_name", sa.String(length=255), nullable=True),
            sa.Column("location", sa.String(length=500), nullable=True),
            sa.Column("remote_policy", sa.String(length=32), nullable=True),
            sa.Column("source_url", sa.String(length=2048), nullable=True),
            sa.Column("description_md", sa.Text(), nullable=True),
            sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            # state ∈ {"new", "interested", "watching", "dismissed", "expired",
            # "promoted"}. "promoted" means a tracked_jobs row was created.
            sa.Column("state", sa.String(length=16), nullable=False, server_default="new", index=True),
            sa.Column(
                "tracked_job_id",
                sa.BigInteger(),
                sa.ForeignKey("tracked_jobs.id", ondelete="SET NULL"),
                nullable=True,
            ),
            # Light score for sort ordering inside the lead inbox.
            sa.Column("relevance_score", sa.Integer(), nullable=True),
            sa.Column("raw_payload", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        # Composite uniqueness so re-polling the same source can't dupe.
        op.create_index(
            "ix_job_leads_source_external",
            _LEADS_TABLE,
            ["source_id", "external_id"],
            unique=True,
        )


def downgrade() -> None:
    if _has_table(_LEADS_TABLE):
        op.drop_index("ix_job_leads_source_external", table_name=_LEADS_TABLE)
        op.drop_table(_LEADS_TABLE)
    if _has_table(_SOURCES_TABLE):
        op.drop_table(_SOURCES_TABLE)
