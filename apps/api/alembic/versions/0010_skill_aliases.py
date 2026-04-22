"""add aliases JSON column to skills

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-22

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has(col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("skills"):
        return False
    return col in {c["name"] for c in insp.get_columns("skills")}


def upgrade() -> None:
    if not _has("aliases"):
        op.add_column("skills", sa.Column("aliases", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has("aliases"):
        op.drop_column("skills", "aliases")
