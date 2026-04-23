"""Generalize job_fetch_queue into a task queue (add kind, payload, label, result).

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-23

Idempotent — each ADD COLUMN is guarded by a column-existence check so running
against a DB whose schema was bootstrapped by Base.metadata.create_all (which
already has the new columns) is a no-op.

Why extend job_fetch_queue rather than create a new table: the existing queue
already owns all the plumbing (state machine, attempts, cooldowns, stuck-row
reset, worker loop). Adding `kind` + `payload` turns it into a general task
queue without a second system to reconcile.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "job_fetch_queue"

_ADDS: list[tuple[str, sa.types.TypeEngine]] = [
    # Kind discriminator — "fetch" for every existing row, then "score",
    # "tailor", "humanize", "strategy", "interview_prep", "org_research", etc.
    ("kind", sa.String(length=32)),
    # Human-friendly label for the Activity page (e.g. "Score: Acme Senior
    # Engineer" or the URL being fetched).
    ("label", sa.String(length=512)),
    # Per-kind JSON args. For kind=fetch, may carry the url; for kind=score,
    # `{tracked_job_id: int}`; for kind=tailor, `{tracked_job_id, doc_type, ...}`.
    ("payload", sa.JSON()),
    # Per-kind JSON result (e.g. {"generated_document_id": 42}).
    ("result", sa.JSON()),
]


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _existing_columns(_TABLE)
    for col, coltype in _ADDS:
        if col in cols:
            continue
        op.add_column(_TABLE, sa.Column(col, coltype, nullable=True))

    # Backfill kind='fetch' on any pre-existing rows so the dispatcher has
    # something to key off. Safe to re-run — only touches NULL rows.
    bind = op.get_bind()
    bind.execute(
        sa.text(f"UPDATE {_TABLE} SET kind='fetch' WHERE kind IS NULL")
    )


def downgrade() -> None:
    cols = _existing_columns(_TABLE)
    for col, _ in _ADDS:
        if col in cols:
            op.drop_column(_TABLE, col)
