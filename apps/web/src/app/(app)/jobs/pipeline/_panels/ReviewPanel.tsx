"use client";

import Link from "next/link";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/swr";

type ReviewItem = {
  id: number;
  title: string;
  organization_id: number | null;
  organization_name: string | null;
  location: string | null;
  date_discovered: string | null;
  fit_score: number | null;
  // Backend now includes both `to_review` (fresh) and `reviewed`
  // (skipped earlier — cycled to the back of the queue) rows.
  status: "to_review" | "reviewed";
};

type ReviewQueueOut = {
  total: number;
  ids: number[];
  items: ReviewItem[];
};

export function ReviewPanel() {
  // Cache key matches the prefetch in usePrefetchHotLists so the data
  // is usually already in memory by the time the user lands here.
  const {
    data,
    error: swrErr,
    isLoading,
  } = useApi<ReviewQueueOut>("/api/v1/jobs/review-queue");
  const loading = isLoading && !data;
  const err =
    swrErr instanceof ApiError
      ? `HTTP ${swrErr.status}`
      : swrErr
        ? "Load failed."
        : null;

  const items = data?.items ?? [];
  const freshCount = items.filter((it) => it.status === "to_review").length;
  const skippedCount = items.filter((it) => it.status === "reviewed").length;
  const firstId = data?.ids?.[0];

  const subtitle = (() => {
    if (items.length === 0) {
      return "Nothing waiting — new jobs land here and you clear them from the detail page.";
    }
    const parts: string[] = [];
    if (freshCount > 0) {
      parts.push(`${freshCount} fresh job${freshCount === 1 ? "" : "s"}`);
    }
    if (skippedCount > 0) {
      parts.push(`${skippedCount} skipped earlier — cycled to the back`);
    }
    return (
      parts.join(" · ") +
      ". Click any to start reviewing, or jump to the first with the button below."
    );
  })();

  return (
    <>
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3">
        <p className="text-sm text-corp-muted">{subtitle}</p>
        {firstId ? (
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
            Inbox zero on job reviews. Nice.
          </p>
          <Link href="/jobs" className="jsp-btn-ghost mt-4 inline-block">
            Back to Tracker
          </Link>
        </div>
      ) : (
        <ul className="jsp-card divide-y divide-corp-border overflow-hidden">
          {items.map((it, i) => {
            const isSkipped = it.status === "reviewed";
            return (
              <li
                key={it.id}
                className={`flex items-center gap-3 py-2 px-4 hover:bg-corp-surface2 ${
                  isSkipped ? "opacity-60" : ""
                }`}
              >
                <span className="text-xs text-corp-muted w-8 text-right shrink-0">
                  #{i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate flex items-center gap-2">
                    <Link
                      href={`/jobs/${it.id}?from=review`}
                      className="hover:text-corp-accent truncate"
                    >
                      {it.title}
                    </Link>
                    {isSkipped ? (
                      <span
                        className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-full border border-corp-accent2/40 bg-corp-accent2/10 text-corp-accent2 shrink-0"
                        title="You skipped this job earlier — it's queued at the back so you can revisit it."
                      >
                        Skipped
                      </span>
                    ) : null}
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
            );
          })}
        </ul>
      )}
    </>
  );
}
