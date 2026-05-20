"""Additional organization fields populated during research.

Adds:
  - sub_industry: finer-grained category than `industry` (e.g.
    "Industrial automation" under industry="Manufacturing"). Useful
    for users with industry-based filter criteria who need finer
    targeting than the one-word industry label.
  - business_model: B2B / B2C / B2G / B2B2C / Mixed. Helps the user
    filter out roles that don't match their target customer.
  - public_or_private: public / private / subsidiary / nonprofit /
    government. Often a hard filter for the user (e.g. "no public
    companies right now") and not derivable from industry alone.

All three are nullable. Backfilled to NULL for existing rows; the
research pipeline will populate them on the next enrichment pass.

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-20

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("organizations", "sub_industry"):
        op.add_column(
            "organizations",
            sa.Column("sub_industry", sa.String(length=128), nullable=True),
        )
    if not _has_column("organizations", "business_model"):
        op.add_column(
            "organizations",
            sa.Column("business_model", sa.String(length=32), nullable=True),
        )
    if not _has_column("organizations", "public_or_private"):
        op.add_column(
            "organizations",
            sa.Column("public_or_private", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    for col in ("public_or_private", "business_model", "sub_industry"):
        if _has_column("organizations", col):
            op.drop_column("organizations", col)
