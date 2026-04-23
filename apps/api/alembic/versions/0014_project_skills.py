"""project_skills junction — dedicated Project ↔ Skill link with usage_notes
(parity with WorkExperienceSkill / CourseSkill).

Today the Project panel attaches skills via the generic `entity_links`
polymorphic table. That works but can't carry per-link `usage_notes`
(e.g. "used Postgres pg_trgm for fuzzy matching"), which is the key
differentiator of the Work/Course junctions.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-23

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "project_skills"


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return insp.has_table(name)


def upgrade() -> None:
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("skill_id", sa.BigInteger(), nullable=False, index=True),
        sa.Column("usage_notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "skill_id", name="uq_project_skill"),
    )


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
