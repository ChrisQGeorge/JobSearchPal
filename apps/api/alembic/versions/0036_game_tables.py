"""The Tower (job-search incremental game): game_ledger + game_state.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "game_ledger" not in tables:
        op.create_table(
            "game_ledger",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("currency", sa.String(16), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(64), nullable=False),
            sa.Column("job_id", sa.BigInteger(), nullable=True),
            sa.Column("note", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("user_id", "reason", "job_id", name="uq_game_ledger_award"),
        )
        op.create_index("ix_game_ledger_user_id", "game_ledger", ["user_id"])
    if "game_state" not in tables:
        op.create_table(
            "game_state",
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("state", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "game_state" in tables:
        op.drop_table("game_state")
    if "game_ledger" in tables:
        op.drop_table("game_ledger")
