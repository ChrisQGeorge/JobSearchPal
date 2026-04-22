"""add resume_after to job_fetch_queue for rate-limit cooldowns

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-22

Idempotent — skips if the column is already present.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("job_fetch_queue"):
        return set()
    return {c["name"] for c in insp.get_columns("job_fetch_queue")}


def upgrade() -> None:
    if "resume_after" not in _existing_columns():
        op.add_column(
            "job_fetch_queue",
            sa.Column("resume_after", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if "resume_after" in _existing_columns():
        op.drop_column("job_fetch_queue", "resume_after")
