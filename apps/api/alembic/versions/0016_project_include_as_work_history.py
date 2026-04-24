"""projects.include_as_work_history — user-opted-in flag for counting a
project's duration toward a skill's total work-history years.

Default FALSE so existing rows don't suddenly inflate every skill's
"work history" number; the user flips it on per-project for open-source
contributions, freelance gigs, and other things that should count.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-23

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "projects"
_COL = "include_as_work_history"


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
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    if _has_col():
        op.drop_column(_TABLE, _COL)
