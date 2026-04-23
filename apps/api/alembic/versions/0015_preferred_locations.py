"""Add preferred_locations JSON column to job_preferences.

List of `{name, max_distance_miles}` entries. Lets the user say "I'd
commute up to 30 mi around Seattle OR 60 mi around Portland" without
coupling to any specific geocoding service (we don't need lat/lng to
match on JDs — we compare on city/region name strings).

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-23

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "job_preferences"
_COL = "preferred_locations"


def _has_col() -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return False
    return _COL in {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_col():
        op.add_column(_TABLE, sa.Column(_COL, sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_col():
        op.drop_column(_TABLE, _COL)
