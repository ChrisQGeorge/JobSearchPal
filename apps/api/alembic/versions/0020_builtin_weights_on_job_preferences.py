"""job_preferences.builtin_weights — per-user weight overrides for the
deterministic fit-score's built-in components (salary, remote_policy,
location, experience_level, employment_type, etc.).

Stored as JSON because the structure is small + bounded; no need for a
junction table. Defaults live in code (app/scoring/fit.py); this column
only stores user overrides.

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-29

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "job_preferences"
_COL = "builtin_weights"


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
