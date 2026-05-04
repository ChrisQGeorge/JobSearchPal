"""job_sources.max_leads_per_poll — cap on how many unique leads any
single poll of a source will create. Default 100; applies to every
source kind (ATS, RSS, Bright Data, etc.) so an over-broad query
doesn't dump thousands of rows into the inbox at once.

Counts only NEW (not-already-deduped) inserts — re-polls don't
re-trigger the cap because dedupe runs first.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-04

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "job_sources"
_COL = "max_leads_per_poll"


def _has_col() -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return False
    return _COL in {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_col():
        op.add_column(
            _TABLE,
            sa.Column(
                _COL,
                sa.Integer(),
                nullable=False,
                server_default=sa.text("100"),
            ),
        )


def downgrade() -> None:
    if _has_col():
        op.drop_column(_TABLE, _COL)
