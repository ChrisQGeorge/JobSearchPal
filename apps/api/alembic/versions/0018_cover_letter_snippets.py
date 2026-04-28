"""cover_letter_snippets — reusable opening hooks, closing lines, and
bridge phrases the user keeps on file to drop into cover letters.

Stored as plain markdown blobs with a `kind` discriminator so the UI can
group them on the library page. The tailor prompt can pull them in by
kind/tags so the model has a stable pool of voice-matched openers and
closers instead of inventing fresh ones every time.

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-28

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "cover_letter_snippets"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return insp.has_table(name)


def upgrade() -> None:
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("kind", sa.String(length=32), nullable=False, index=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("content_md", sa.Text(), nullable=False),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
