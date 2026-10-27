"""Sol outbox (GitHub repo hand-off): outbox_config + outbox_jobs.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "outbox_config" not in tables:
        op.create_table(
            "outbox_config",
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("config", sa.JSON(), nullable=False),
            sa.Column("state", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "outbox_jobs" not in tables:
        op.create_table(
            "outbox_jobs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tracked_job_id", sa.BigInteger(), sa.ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("job_ref", sa.String(40), nullable=False),
            sa.Column("slug", sa.String(120), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_files", sa.JSON(), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("withdraw_reason", sa.String(500), nullable=True),
            sa.Column("withdrawn_published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sol_status", sa.String(16), nullable=True),
            sa.Column("sol_status_at", sa.String(40), nullable=True),
            sa.Column("sol_confirmation", sa.String(200), nullable=True),
            sa.Column("sol_note", sa.String(500), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("user_id", "job_ref", name="uq_outbox_job_ref"),
        )
        op.create_index("ix_outbox_jobs_user_id", "outbox_jobs", ["user_id"])
        op.create_index("ix_outbox_jobs_tracked_job_id", "outbox_jobs", ["tracked_job_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "outbox_jobs" in tables:
        op.drop_table("outbox_jobs")
    if "outbox_config" in tables:
        op.drop_table("outbox_config")
