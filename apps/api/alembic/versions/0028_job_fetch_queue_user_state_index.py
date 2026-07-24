"""Composite (user_id, state) index on job_fetch_queue.

The activity feed now computes per-state counts over the whole table on
every poll (`GROUP BY state` filtered by user), and the bulk clear
endpoint deletes by (user_id, state IN …). Both were served by the two
single-column indexes before, which lets MySQL use only one of them.
A composite covers the filter + group in one index read.

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-24

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    existing = _existing_indexes("job_fetch_queue")
    if "ix_job_fetch_queue_user_state" not in existing:
        op.create_index(
            "ix_job_fetch_queue_user_state",
            "job_fetch_queue",
            ["user_id", "state"],
        )


def downgrade() -> None:
    existing = _existing_indexes("job_fetch_queue")
    if "ix_job_fetch_queue_user_state" in existing:
        op.drop_index(
            "ix_job_fetch_queue_user_state", table_name="job_fetch_queue"
        )
