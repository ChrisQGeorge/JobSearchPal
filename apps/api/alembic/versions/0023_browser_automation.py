"""R10 browser-automation tables.

Three new tables:

  - application_run: one row per "the Companion attempts to apply to
    a tracked job" attempt. Holds state machine (queued / running /
    awaiting_user / submitted / failed) plus cost + transcript paths.
  - application_run_step: granular event log per run (navigate / fill /
    click / screenshot / ask_user / answer / submit). The /applications
    page replays this to show what the agent actually did.
  - question_answer: the question-bank. SHA-1 of the normalized
    question text → user's stored answer. Reused across every future
    application that hits the same question.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-13

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return insp.has_table(name)


def upgrade() -> None:
    if not _has_table("application_run"):
        op.create_table(
            "application_run",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "tracked_job_id",
                sa.BigInteger(),
                sa.ForeignKey("tracked_jobs.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            # tier ∈ "ats" (R11 templates) | "generic" (R10 agent loop only)
            sa.Column("tier", sa.String(length=16), nullable=False, server_default="generic"),
            # state ∈ queued | running | awaiting_user | submitted | failed | cancelled
            sa.Column("state", sa.String(length=16), nullable=False, server_default="queued", index=True),
            sa.Column("ats_kind", sa.String(length=32), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("queue_id", sa.BigInteger(), nullable=True),
            sa.Column("transcript_path", sa.String(length=512), nullable=True),
            sa.Column("screenshot_dir", sa.String(length=512), nullable=True),
            sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            # Pending question for the user when state=awaiting_user.
            sa.Column("pending_question", sa.Text(), nullable=True),
            sa.Column("pending_question_hash", sa.String(length=40), nullable=True),
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

    if not _has_table("application_run_step"):
        op.create_table(
            "application_run_step",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "run_id",
                sa.BigInteger(),
                sa.ForeignKey("application_run.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "ts",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            # kind ∈ navigate | click | type | screenshot | dom_read |
            #        ask_user | answer | submit | error | note
            sa.Column("kind", sa.String(length=32), nullable=False, index=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("screenshot_url", sa.String(length=1024), nullable=True),
        )

    if not _has_table("question_answer"):
        op.create_table(
            "question_answer",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("question_hash", sa.String(length=40), nullable=False, index=True),
            sa.Column("question_text", sa.String(length=2000), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.UniqueConstraint("user_id", "question_hash", name="uq_question_answer_user_hash"),
        )


def downgrade() -> None:
    if _has_table("application_run_step"):
        op.drop_table("application_run_step")
    if _has_table("application_run"):
        op.drop_table("application_run")
    if _has_table("question_answer"):
        op.drop_table("question_answer")
