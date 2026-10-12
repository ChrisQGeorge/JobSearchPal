"""tracked_jobs.awaiting_human_resolution — the human's answer to an
agent's awaiting_human request, read by the agent before retrying.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-12
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("tracked_jobs")}
    if "awaiting_human_resolution" not in cols:
        op.add_column("tracked_jobs", sa.Column("awaiting_human_resolution", sa.Text(), nullable=True))


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("tracked_jobs")}
    if "awaiting_human_resolution" in cols:
        op.drop_column("tracked_jobs", "awaiting_human_resolution")
