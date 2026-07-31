"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { getScoredOnly, setScoredOnly } from "@/lib/queuePrefs";

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
  const [data, setData] = useState<ReviewQueueOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // Persisted: the detail page's "Next →" nav reads the same key, so
  // the flow keeps skipping unscored jobs after you start reviewing.
  const [scoredOnly, setScoredOnlyState] = useState(getScoredOnly);

  function toggleScoredOnly(v: boolean) {
    setScoredOnlyState(v);
    setScoredOnly(v);
  }

  useEffect(() => {
    setLoading(true);
    api
      .get<ReviewQueueOut>(
        `/api/v1/jobs/review-queue${scoredOnly ? "?scored_only=true" : ""}`,
      )
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e) =>
        setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed."),
      )
      .finally(() => setLoading(false));
  }, [scoredOnly]);

  const items = data?.items ?? [];
  const freshCount = items.filter((it) => it.status === "to_review").length;
  const skippedCount = items.filter((it) => it.status === "reviewed").length;
  const firstId = data?.ids?.[0];

  const subtitle = (() => {
    if (items.length === 0) {
      return scoredOnly
        ? "No scored jobs waiting. The queue worker may still be analyzing — or un-check the filter to review unscored ones."
        : "Nothing waiting — new jobs land here and you clear them from the detail page.";
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
        <div className="flex items-center gap-3">
          <label
            className="flex items-center gap-1.5 text-xs text-corp-muted cursor-pointer select-none"
            title="Only cycle through jobs that already have a fit score. The Next → navigation on the detail page follows this too."
          >
            <input
              type="checkbox"
              className="accent-corp-accent"
              checked={scoredOnly}
              onChange={(e) => toggleScoredOnly(e.target.checked)}
            />
            Scored jobs only
          </label>
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
            {scoredOnly
              ? "No scored jobs in the review queue right now."
              : "Inbox zero on job reviews. Nice."}
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
