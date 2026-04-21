"""add explicit tracked_jobs fields: experience, employment, education, visa, relocation, required/nice-to-have skills

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-21

Idempotent: each column-add checks for current presence first so running this
on a DB that was initialized from the updated create_all (which already has
the columns) is a no-op.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    ("experience_years_min", sa.Integer()),
    ("experience_years_max", sa.Integer()),
    ("experience_level", sa.String(length=32)),
    ("employment_type", sa.String(length=32)),
    ("education_required", sa.String(length=64)),
    ("visa_sponsorship_offered", sa.Boolean()),
    ("relocation_offered", sa.Boolean()),
    ("required_skills", sa.JSON()),
    ("nice_to_have_skills", sa.JSON()),
]


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("tracked_jobs"):
        return set()
    return {c["name"] for c in insp.get_columns("tracked_jobs")}


def upgrade() -> None:
    have = _existing_columns()
    for name, col_type in _NEW_COLUMNS:
        if name in have:
            continue
        op.add_column("tracked_jobs", sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    have = _existing_columns()
    for name, _ in reversed(_NEW_COLUMNS):
        if name in have:
            op.drop_column("tracked_jobs", name)
