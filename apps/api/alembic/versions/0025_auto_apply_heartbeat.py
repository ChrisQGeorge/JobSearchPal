"""R11 — gate auto-apply on a /browser-page visibility heartbeat.

Adds `last_browser_visible_at` to `auto_apply_settings`. The web app's
/browser page posts a heartbeat every ~10s while the tab is visible
(Page Visibility API). The auto-apply poller refuses to spawn new
runs when the heartbeat is stale (older than the configured grace
window) — so the agent only fires when the user has the browser
stream on-screen and can step in.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-15

Idempotent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("auto_apply_settings", "last_browser_visible_at"):
        op.add_column(
            "auto_apply_settings",
            sa.Column(
                "last_browser_visible_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    if _has_column("auto_apply_settings", "last_browser_visible_at"):
        op.drop_column("auto_apply_settings", "last_browser_visible_at")
