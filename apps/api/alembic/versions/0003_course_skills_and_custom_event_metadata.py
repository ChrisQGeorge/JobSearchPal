"""add course_skills + rename custom_events.metadata -> event_metadata

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-21

Idempotent: both operations check current schema state before mutating, so
running this on a database that was created fresh from the updated 0001 (which
already has the new columns via create_all) is a no-op.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    # --- course_skills join table ------------------------------------------
    if not _table_exists("course_skills"):
        op.create_table(
            "course_skills",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("course_id", sa.BigInteger(), nullable=False, index=True),
            sa.Column("skill_id", sa.BigInteger(), nullable=False, index=True),
            sa.Column("usage_notes", sa.Text(), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["course_id"], ["courses.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["skill_id"], ["skills.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint("course_id", "skill_id", name="uq_course_skill"),
        )

    # --- custom_events: metadata → event_metadata --------------------------
    # 0001 using create_all may have produced either the old column (`metadata`)
    # or the new one (`event_metadata`) depending on when it ran. Normalise.
    if _column_exists("custom_events", "metadata") and not _column_exists(
        "custom_events", "event_metadata"
    ):
        # Safe rename: keeps any existing JSON values.
        with op.batch_alter_table("custom_events") as b:
            b.alter_column(
                "metadata",
                new_column_name="event_metadata",
                existing_type=sa.JSON(),
                existing_nullable=True,
            )
    elif _column_exists("custom_events", "metadata") and _column_exists(
        "custom_events", "event_metadata"
    ):
        # Both present (unlikely). Drop the legacy one; event_metadata wins.
        with op.batch_alter_table("custom_events") as b:
            b.drop_column("metadata")


def downgrade() -> None:
    if _column_exists("custom_events", "event_metadata") and not _column_exists(
        "custom_events", "metadata"
    ):
        with op.batch_alter_table("custom_events") as b:
            b.alter_column(
                "event_metadata",
                new_column_name="metadata",
                existing_type=sa.JSON(),
                existing_nullable=True,
            )
    if _table_exists("course_skills"):
        op.drop_table("course_skills")
