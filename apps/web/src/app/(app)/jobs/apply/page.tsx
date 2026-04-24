"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

type ApplyItem = {
  id: number;
  title: string;
  organization_id: number | null;
  organization_name: string | null;
  location: string | null;
  date_discovered: string | null;
  fit_score: number | null;
};

type ApplyQueueOut = {
  total: number;
  ids: number[];
  items: ApplyItem[];
};

export default function ApplyQueuePage() {
  const [data, setData] = useState<ApplyQueueOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ApplyQueueOut>("/api/v1/jobs/apply-queue")
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e) =>
        setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed."),
      )
      .finally(() => setLoading(false));
  }, []);

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const firstId = data?.ids?.[0];

  return (
    <PageShell
      title="Apply Queue"
      subtitle={
        total === 0
          ? "Nothing queued — mark jobs as 'interested' in the review queue to stack them here."
          : `${total} job${total === 1 ? "" : "s"} you've flagged as interested. Work through them one by one with the apply-flow buttons on each detail page.`
      }
      actions={
        firstId ? (
          <Link
            href={`/jobs/${firstId}?from=apply`}
            className="jsp-btn-primary"
          >
            Start applying →
          </Link>
        ) : (
          <Link href="/jobs" className="jsp-btn-ghost">
            Back to Tracker
          </Link>
        )
      }
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger">{err}</div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <div className="jsp-card p-8 text-center">
          <div className="text-3xl mb-2">✓</div>
          <p className="text-sm text-corp-muted">
            No jobs waiting to apply to. Triage the Review Queue first or
            mark existing rows "interested" on the tracker.
          </p>
          <Link
            href="/jobs/review"
            className="jsp-btn-ghost mt-4 inline-block"
          >
            Open Review Queue
          </Link>
        </div>
      ) : (
        <ul className="jsp-card divide-y divide-corp-border overflow-hidden">
          {items.map((it, i) => (
            <li
              key={it.id}
              className="flex items-center gap-3 py-2 px-4 hover:bg-corp-surface2"
            >
              <span className="text-xs text-corp-muted w-8 text-right shrink-0">
                #{i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm truncate">
                  <Link
                    href={`/jobs/${it.id}?from=apply`}
                    className="hover:text-corp-accent"
                  >
                    {it.title}
                  </Link>
                </div>
                <div className="text-xs text-corp-muted truncate">
                  {[
                    it.organization_name,
                    it.location,
                    it.date_discovered
                      ? `discovered ${it.date_discovered}`
                      : null,
                    it.fit_score != null ? `fit ${it.fit_score}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </div>
              <Link
                href={`/jobs/${it.id}?from=apply`}
                className="jsp-btn-ghost text-xs shrink-0"
              >
                Open →
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}
