"""R11 auto-apply per-user settings.

Single-row-per-user table holding the user's auto-apply policy:
on/off, daily cap, minimum fit-score gate, optional dry-run mode.
The Companion poller reads it on every tick and only fires
`apply_run` rows when enabled and within budget.

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-15

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return insp.has_table(name)


def upgrade() -> None:
    if _has_table("auto_apply_settings"):
        return
    op.create_table(
        "auto_apply_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("daily_cap", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("min_fit_score", sa.Integer(), nullable=True),
        sa.Column("only_known_ats", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        # Pause window — if set, the poller skips ticks whose hour-of-day
        # falls inside [pause_start_hour, pause_end_hour). Both nullable so
        # the user can leave the schedule wide open.
        sa.Column("pause_start_hour", sa.Integer(), nullable=True),
        sa.Column("pause_end_hour", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
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
    if _has_table("auto_apply_settings"):
        op.drop_table("auto_apply_settings")
