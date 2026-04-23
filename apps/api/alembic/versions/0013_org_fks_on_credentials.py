"""Add organization_id FK columns to achievements, certifications,
publications, and volunteer_works so the UI can offer an Organization
combobox instead of free-text (per feature request). Free-text columns
stay in place so existing data isn't disrupted — new writes populate both.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-23

Idempotent — each ADD COLUMN is guarded so re-running against a
create_all-bootstrapped schema is a no-op.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ADDS: list[tuple[str, str]] = [
    ("achievements", "organization_id"),
    ("certifications", "organization_id"),
    ("publications", "organization_id"),
    ("volunteer_works", "organization_id"),
]


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table, col in _ADDS:
        if col in _existing_columns(table):
            continue
        op.add_column(
            table,
            sa.Column(
                col,
                sa.BigInteger(),
                sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
        )


def downgrade() -> None:
    for table, col in _ADDS:
        if col in _existing_columns(table):
            op.drop_column(table, col)
