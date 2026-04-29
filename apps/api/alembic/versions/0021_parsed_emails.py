"""parsed_emails — log of every email the user has run through the
email-ingest skill, with the classifier output, the matched tracked
job (if any), and whether the suggested action was applied.

We keep ALL parsed emails (including unmatched / unrelated ones) so
the user can revisit, correct a misclassification, or dedupe a forward
that arrived twice.

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-29

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "parsed_emails"


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
            # Sender / subject / body — verbatim. We keep this in the DB
            # so the user can re-classify an old email without keeping
            # the original mailbox connection live.
            sa.Column("from_address", sa.String(length=320), nullable=True),
            sa.Column("subject", sa.String(length=512), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("body_md", sa.Text(), nullable=True),
            # Hash of (from + subject + received_at + body) — used to
            # dedupe re-pastes of the same email. Hex digest of SHA-1.
            sa.Column("dedupe_hash", sa.String(length=40), nullable=True, index=True),
            # Classifier output JSON. Shape:
            # { intent: str, confidence: float, suggested_status: str|null,
            #   suggested_event_type: str|null, suggested_round_outcome: str|null,
            #   reasoning: str, key_dates: [iso strings], ... }
            sa.Column("classification", sa.JSON(), nullable=True),
            # Matched tracked job, set after Claude returns (may be null
            # if the email doesn't reference a tracked role).
            sa.Column(
                "tracked_job_id",
                sa.BigInteger(),
                sa.ForeignKey("tracked_jobs.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            # state ∈ "new" (parsed, awaiting review) | "applied" (user
            # confirmed and the suggested action ran) | "dismissed" (user
            # rejected the suggestion) | "errored" (parse failed)
            sa.Column("state", sa.String(length=16), nullable=False, server_default="new", index=True),
            sa.Column(
                "applied_event_id",
                sa.BigInteger(),
                sa.ForeignKey("application_events.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
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
        )


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
