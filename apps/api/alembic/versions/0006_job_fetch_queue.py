"""add job_fetch_queue table

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-21
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if _table_exists("job_fetch_queue"):
        return
    op.create_table(
        "job_fetch_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("desired_status", sa.String(length=32), nullable=True),
        sa.Column("desired_priority", sa.String(length=16), nullable=True),
        sa.Column("desired_date_applied", sa.Date(), nullable=True),
        sa.Column("desired_date_closed", sa.Date(), nullable=True),
        sa.Column("desired_notes", sa.Text(), nullable=True),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="queued",
            index=True,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_tracked_job_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_tracked_job_id"],
            ["tracked_jobs.id"],
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    if _table_exists("job_fetch_queue"):
        op.drop_table("job_fetch_queue")
