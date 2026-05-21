"use client";

import Link from "next/link";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/swr";

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

export function ApplyPanel() {
  // Cache key matches the prefetch in usePrefetchHotLists so the queue
  // is hydrated before the user clicks into it.
  const {
    data,
    error: swrErr,
    isLoading,
  } = useApi<ApplyQueueOut>("/api/v1/jobs/apply-queue");
  const loading = isLoading && !data;
  const err =
    swrErr instanceof ApiError
      ? `HTTP ${swrErr.status}`
      : swrErr
        ? "Load failed."
        : null;

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const firstId = data?.ids?.[0];

  const subtitle =
    total === 0
      ? "Nothing queued — mark jobs as 'interested' in the review queue to stack them here."
      : `${total} job${total === 1 ? "" : "s"} you've flagged as interested. Work through them one by one with the apply-flow buttons on each detail page.`;

  return (
    <>
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3">
        <p className="text-sm text-corp-muted">{subtitle}</p>
        {firstId ? (
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
        )}
      </div>

      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger">{err}</div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <div className="jsp-card p-8 text-center">
          <div className="text-3xl mb-2">✓</div>
          <p className="text-sm text-corp-muted">
            No jobs waiting to apply to. Triage the Review tab first or
            mark existing rows "interested" on the tracker.
          </p>
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
    </>
  );
}
