"""add entity_links polymorphic relationship table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-21
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if _table_exists("entity_links"):
        return
    op.create_table(
        "entity_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("from_entity_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("from_entity_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("to_entity_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("to_entity_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("relation", sa.String(length=32), nullable=False, server_default="related"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id",
            "from_entity_type",
            "from_entity_id",
            "to_entity_type",
            "to_entity_id",
            "relation",
            name="uq_entity_link",
        ),
    )


def downgrade() -> None:
    if _table_exists("entity_links"):
        op.drop_table("entity_links")
