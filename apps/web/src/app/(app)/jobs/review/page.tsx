"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

type ReviewItem = {
  id: number;
  title: string;
  organization_id: number | null;
  organization_name: string | null;
  location: string | null;
  date_discovered: string | null;
  fit_score: number | null;
};

type ReviewQueueOut = {
  total: number;
  ids: number[];
  items: ReviewItem[];
};

export default function ReviewQueuePage() {
  const [data, setData] = useState<ReviewQueueOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ReviewQueueOut>("/api/v1/jobs/review-queue")
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
      title="Review Queue"
      subtitle={
        total === 0
          ? "Nothing waiting — new jobs land here and you clear them from the detail page."
          : `${total} job${total === 1 ? "" : "s"} waiting on your attention. Click any to start reviewing, or jump to the first with the button below.`
      }
      actions={
        firstId ? (
          <Link
            href={`/jobs/${firstId}?from=review`}
            className="jsp-btn-primary"
          >
            Start reviewing →
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
            Inbox zero on job reviews. Nice.
          </p>
          <Link href="/jobs" className="jsp-btn-ghost mt-4 inline-block">
            Back to Tracker
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
                    href={`/jobs/${it.id}?from=review`}
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
                href={`/jobs/${it.id}?from=review`}
                className="jsp-btn-ghost text-xs shrink-0"
              >
                Review →
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}
