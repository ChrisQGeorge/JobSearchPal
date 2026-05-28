"""Performance indexes for tracked_jobs.

The app got noticeably slower as the tracked_jobs row count grew into the
thousands. Two query shapes dominate and neither had good index support:

  1. Queue + tracker queries filter on
       user_id = ? AND status (IN …) AND deleted_at IS NULL
     `user_id` and `status` were each indexed individually, so MySQL
     could only use one and scanned the rest. A composite covering all
     three filter columns lets it satisfy the WHERE from the index.

  2. URL dedup (`_find_existing_job_by_url`) filters on
       user_id = ? AND source_url IN (…) AND deleted_at IS NULL
     `source_url` had no index at all, so every import did a full scan.
     A (user_id, source_url) index turns it into a point lookup.

source_url is VARCHAR(2048); MySQL's index-prefix limit on utf8mb4 is
767 bytes (191 chars) without innodb_large_prefix, but modern MySQL 8
defaults allow up to 3072 bytes. We cap the indexed prefix at 255 chars
to stay comfortably under limits while still being highly selective —
job URLs are unique well within their first 255 chars.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-27

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    existing = _existing_indexes("tracked_jobs")

    if "ix_tracked_jobs_user_status_deleted" not in existing:
        op.create_index(
            "ix_tracked_jobs_user_status_deleted",
            "tracked_jobs",
            ["user_id", "status", "deleted_at"],
        )

    # Prefix-limited index on source_url (long VARCHAR). Raw SQL because
    # alembic's create_index doesn't expose MySQL prefix lengths portably.
    if "ix_tracked_jobs_user_source_url" not in existing:
        op.execute(
            "CREATE INDEX ix_tracked_jobs_user_source_url "
            "ON tracked_jobs (user_id, source_url(255))"
        )


def downgrade() -> None:
    existing = _existing_indexes("tracked_jobs")
    if "ix_tracked_jobs_user_source_url" in existing:
        op.drop_index("ix_tracked_jobs_user_source_url", table_name="tracked_jobs")
    if "ix_tracked_jobs_user_status_deleted" in existing:
        op.drop_index(
            "ix_tracked_jobs_user_status_deleted", table_name="tracked_jobs"
        )
