"""add desired_date_posted to job_fetch_queue

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-21

Idempotent: checks whether the column is already present (e.g. from a fresh
create_all) and skips if so.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("job_fetch_queue"):
        return set()
    return {c["name"] for c in insp.get_columns("job_fetch_queue")}


def upgrade() -> None:
    have = _existing_columns()
    if "desired_date_posted" not in have:
        op.add_column(
            "job_fetch_queue",
            sa.Column("desired_date_posted", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    have = _existing_columns()
    if "desired_date_posted" in have:
        op.drop_column("job_fetch_queue", "desired_date_posted")
