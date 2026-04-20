"""companion conversations: add claude_session_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-20

Idempotent: if 0001 already created the column (because it was applied against
a model state that included it), this migration is a no-op.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    if not _column_exists("companion_conversations", "claude_session_id"):
        op.add_column(
            "companion_conversations",
            sa.Column("claude_session_id", sa.String(length=128), nullable=True),
        )


def downgrade() -> None:
    if _column_exists("companion_conversations", "claude_session_id"):
        op.drop_column("companion_conversations", "claude_session_id")
