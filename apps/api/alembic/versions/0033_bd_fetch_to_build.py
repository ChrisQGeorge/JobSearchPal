"""Turn pending/failed page-fetch tasks for Bright Data leads into builds.

Before the fix, adding Bright Data leads to the tracker queued ordinary
page fetches (fetch + LLM parse) whenever the stored record lacked a
`job_posting_id` key. This rewrites every fetch task that is still
queued, processing, or failed — and belongs to a lead from a Bright Data
source — into a "build from Bright Data data" task: payload gets
prefetched=brightdata_linkedin (the worker builds the job from the
lead's stored record / fields, never fetching the page) and failed or
interrupted ones go back to the queue with attempts reset.

Skipped: tasks that already created their job, and leads already linked
to a tracked job (no duplicates). Finished tasks are untouched.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-12

Data-only and idempotent; downgrade is a no-op.
"""
from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH = 500


def upgrade() -> None:
    bind = op.get_bind()
    last_id = 0
    converted = requeued = 0
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT q.id, q.payload, q.state, l.title "
                "FROM job_fetch_queue q "
                "JOIN job_leads l ON l.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(q.payload, '$.lead_id')) AS UNSIGNED) "
                "JOIN job_sources s ON s.id = l.source_id "
                "WHERE q.id > :last "
                "AND (q.kind = 'fetch' OR q.kind IS NULL) "
                "AND q.state IN ('queued', 'processing', 'error') "
                "AND q.created_tracked_job_id IS NULL "
                "AND l.tracked_job_id IS NULL "
                "AND s.kind LIKE 'brightdata%' "
                "ORDER BY q.id LIMIT :n"
            ),
            {"last": last_id, "n": BATCH},
        ).fetchall()
        if not rows:
            break
        for qid, payload, state, title in rows:
            last_id = qid
            if isinstance(payload, (bytes, str)):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    payload = None
            if not isinstance(payload, dict):
                continue
            if payload.get("prefetched") and state == "queued":
                continue  # already a build task
            payload["prefetched"] = "brightdata_linkedin"
            params = {
                "id": qid,
                "payload": json.dumps(payload),
                "label": f"Build from Bright Data data → {(title or 'job')[:80]}"[:512],
            }
            if state in ("error", "processing"):
                bind.execute(
                    sa.text(
                        "UPDATE job_fetch_queue SET payload = :payload, label = :label, "
                        "state = 'queued', attempts = 0, error_message = NULL, "
                        "resume_after = NULL WHERE id = :id"
                    ),
                    params,
                )
                requeued += 1
            else:
                bind.execute(
                    sa.text(
                        "UPDATE job_fetch_queue SET payload = :payload, label = :label WHERE id = :id"
                    ),
                    params,
                )
            converted += 1
    print(f"0033: converted {converted} Bright Data fetch tasks to builds ({requeued} failed/interrupted re-queued)")


def downgrade() -> None:
    pass
