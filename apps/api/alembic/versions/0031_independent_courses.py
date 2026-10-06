"""Courses become independent of Education.

- courses.user_id (NOT NULL) — backfilled from each course's education.
- courses.education_id becomes NULLABLE; its FK switches from
  ON DELETE CASCADE to ON DELETE SET NULL (a deleted education unlinks
  its courses instead of destroying them).
- courses.organization_id — provider for standalone courses.
- courses.certification_id — the credential a course led to.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-06

Idempotent: every step checks current schema first.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

T = "courses"


def _insp():
    return sa.inspect(op.get_bind())


def _cols() -> dict[str, dict]:
    return {c["name"]: c for c in _insp().get_columns(T)}


def _fks() -> list[dict]:
    return _insp().get_foreign_keys(T)


def _ixs() -> set[str]:
    return {ix["name"] for ix in _insp().get_indexes(T)}


def upgrade() -> None:
    cols = _cols()

    # 1. Owner column, backfilled from the parent education.
    if "user_id" not in cols:
        op.add_column(T, sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE courses c JOIN educations e ON e.id = c.education_id "
        "SET c.user_id = e.user_id WHERE c.user_id IS NULL"
    )
    # Orphans (no resolvable owner) can't be shown to anyone — drop them
    # so the NOT NULL constraint can apply. CASCADE meant there shouldn't
    # be any, but be safe.
    op.execute("DELETE FROM course_skills WHERE course_id IN (SELECT id FROM (SELECT id FROM courses WHERE user_id IS NULL) x)")
    op.execute("DELETE FROM courses WHERE user_id IS NULL")
    if _cols()["user_id"]["nullable"]:
        op.alter_column(T, "user_id", existing_type=sa.BigInteger(), nullable=False)
    if "ix_courses_user_id" not in _ixs():
        op.create_index("ix_courses_user_id", T, ["user_id"])
    if not any(fk["constrained_columns"] == ["user_id"] for fk in _fks()):
        op.create_foreign_key(
            "fk_courses_user_id", T, "users", ["user_id"], ["id"], ondelete="CASCADE"
        )

    # 2. education_id: nullable + SET NULL on delete.
    for fk in _fks():
        if fk["constrained_columns"] == ["education_id"] and (
            (fk.get("options") or {}).get("ondelete", "").upper() != "SET NULL"
        ):
            op.drop_constraint(fk["name"], T, type_="foreignkey")
    if _cols()["education_id"]["nullable"] is False:
        op.alter_column(T, "education_id", existing_type=sa.BigInteger(), nullable=True)
    if not any(fk["constrained_columns"] == ["education_id"] for fk in _fks()):
        op.create_foreign_key(
            "fk_courses_education_id", T, "educations", ["education_id"], ["id"],
            ondelete="SET NULL",
        )

    # 3. Provider + resulting certification.
    for col, target in (("organization_id", "organizations"), ("certification_id", "certifications")):
        if col not in _cols():
            op.add_column(T, sa.Column(col, sa.BigInteger(), nullable=True))
        ix = f"ix_courses_{col}"
        if ix not in _ixs():
            op.create_index(ix, T, [col])
        if not any(fk["constrained_columns"] == [col] for fk in _fks()):
            op.create_foreign_key(
                f"fk_courses_{col}", T, target, [col], ["id"], ondelete="SET NULL"
            )


def downgrade() -> None:
    # Standalone courses have no education to fall back to; they're
    # removed so education_id can return to NOT NULL.
    for fk in _fks():
        if fk["constrained_columns"] in (["organization_id"], ["certification_id"], ["user_id"], ["education_id"]):
            op.drop_constraint(fk["name"], T, type_="foreignkey")
    for col in ("organization_id", "certification_id"):
        ix = f"ix_courses_{col}"
        if ix in _ixs():
            op.drop_index(ix, table_name=T)
        if col in _cols():
            op.drop_column(T, col)
    op.execute("DELETE FROM course_skills WHERE course_id IN (SELECT id FROM (SELECT id FROM courses WHERE education_id IS NULL) x)")
    op.execute("DELETE FROM courses WHERE education_id IS NULL")
    op.alter_column(T, "education_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_foreign_key(
        "fk_courses_education_id", T, "educations", ["education_id"], ["id"], ondelete="CASCADE"
    )
    if "ix_courses_user_id" in _ixs():
        op.drop_index("ix_courses_user_id", table_name=T)
    if "user_id" in _cols():
        op.drop_column(T, "user_id")
