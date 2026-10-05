"""generated_documents.prompt_variant — which prompt variant wrote a doc.

Feeds the A/B outcome stats on Settings → Prompts.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-05

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "generated_documents"
_COL = "prompt_variant"
_IX = "ix_generated_documents_prompt_variant"


def _cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(_TABLE)}


def _ixs() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {ix["name"] for ix in insp.get_indexes(_TABLE)}


def upgrade() -> None:
    if _COL not in _cols():
        op.add_column(_TABLE, sa.Column(_COL, sa.String(96), nullable=True))
    if _IX not in _ixs():
        op.create_index(_IX, _TABLE, [_COL])


def downgrade() -> None:
    if _IX in _ixs():
        op.drop_index(_IX, table_name=_TABLE)
    if _COL in _cols():
        op.drop_column(_TABLE, _COL)
