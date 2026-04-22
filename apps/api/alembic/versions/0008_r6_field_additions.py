"""R6 field additions: work.remote_policy, education.concentration,
course dates, contact.can_use_as_reference.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-22

Idempotent: each column-add checks whether it's already present so running
on a DB that was bootstrapped by create_all (which already has the columns)
is a no-op.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ADDS: list[tuple[str, str, sa.types.TypeEngine]] = [
    ("work_experiences", "remote_policy", sa.String(length=16)),
    ("educations", "concentration", sa.String(length=255)),
    ("courses", "start_date", sa.Date()),
    ("courses", "end_date", sa.Date()),
    ("contacts", "can_use_as_reference", sa.String(length=16)),
]


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table, col, coltype in _ADDS:
        if col in _existing_columns(table):
            continue
        op.add_column(table, sa.Column(col, coltype, nullable=True))


def downgrade() -> None:
    for table, col, _ in _ADDS:
        if col in _existing_columns(table):
            op.drop_column(table, col)
