"""tracked_jobs.awaiting_human_reason — the problem an external agent needs a
human for (shown while status=awaiting_human).

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-12
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("tracked_jobs")}
    if "awaiting_human_reason" not in cols:
        op.add_column("tracked_jobs", sa.Column("awaiting_human_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("tracked_jobs")}
    if "awaiting_human_reason" in cols:
        op.drop_column("tracked_jobs", "awaiting_human_reason")
