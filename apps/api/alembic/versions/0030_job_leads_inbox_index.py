"""Composite (user_id, state, first_seen_at) index on job_leads.

The paged inbox filters by user + state, orders by first_seen_at and
counts the total on every page load; with Bright Data runs adding
thousands of leads at a time, one composite index serves all three.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-07

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IX = "ix_job_leads_user_state_seen"


def _existing() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("job_leads"):
        return set()
    return {ix["name"] for ix in insp.get_indexes("job_leads")}


def upgrade() -> None:
    if _IX not in _existing():
        op.create_index(_IX, "job_leads", ["user_id", "state", "first_seen_at"])


def downgrade() -> None:
    if _IX in _existing():
        op.drop_index(_IX, table_name="job_leads")
