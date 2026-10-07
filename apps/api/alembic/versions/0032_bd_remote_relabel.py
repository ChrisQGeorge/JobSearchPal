"""Re-derive remote_policy for Bright Data leads (and the jobs made from them).

The importer used to fall back to the search row's `remote` filter when a
record had no workplace field, labelling every result of a "Remote" row
remote. LinkedIn's public search ignores that filter, so on-site jobs were
labelled remote. This re-derives each Bright Data lead's label from its
stored record using only explicit workplace fields or "remote" in the
location — unknown becomes NULL — and applies the same correction to a
tracked job created from the lead, but only while the job still carries
exactly the lead's old label (a value the user set differently is left
alone).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-07

Data-only and idempotent; downgrade is a no-op.
"""
from __future__ import annotations

import json
import re
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH = 500


def _derive(rec: object, location: Optional[str]) -> Optional[str]:
    """Mirror of brightdata._remote_from_record (kept inline so the
    migration doesn't change if the app code does)."""
    if isinstance(rec, dict):
        for key in ("job_workplace_type", "workplace_type"):
            v = str(rec.get(key) or "").lower()
            if "remote" in v:
                return "remote"
            if "hybrid" in v:
                return "hybrid"
            if "on-site" in v or "onsite" in v:
                return "onsite"
        location = location or rec.get("job_location") or rec.get("location")
    if re.search(r"\bremote\b", str(location or ""), re.I):
        return "remote"
    return None


def upgrade() -> None:
    bind = op.get_bind()
    last_id = 0
    leads_fixed = jobs_fixed = 0
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT l.id, l.remote_policy, l.location, l.raw_payload, l.tracked_job_id "
                "FROM job_leads l JOIN job_sources s ON s.id = l.source_id "
                "WHERE s.kind LIKE 'brightdata%' AND l.id > :last "
                "AND l.remote_policy IS NOT NULL "
                "ORDER BY l.id LIMIT :n"
            ),
            {"last": last_id, "n": BATCH},
        ).fetchall()
        if not rows:
            break
        for lid, old, location, raw, job_id in rows:
            last_id = lid
            if isinstance(raw, (bytes, str)):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = None
            if raw is None:
                continue  # no record to re-derive from — leave it
            new = _derive(raw, location)
            if new == old:
                continue
            bind.execute(
                sa.text("UPDATE job_leads SET remote_policy = :v WHERE id = :id"),
                {"v": new, "id": lid},
            )
            leads_fixed += 1
            if job_id:
                res = bind.execute(
                    sa.text(
                        "UPDATE tracked_jobs SET remote_policy = :v "
                        "WHERE id = :id AND remote_policy = :old"
                    ),
                    {"v": new, "id": job_id, "old": old},
                )
                jobs_fixed += res.rowcount or 0
    print(f"0032: relabelled {leads_fixed} Bright Data leads, {jobs_fixed} tracked jobs")


def downgrade() -> None:
    pass
