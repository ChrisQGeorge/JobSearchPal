"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { getScoredOnly, setScoredOnly } from "@/lib/queuePrefs";

type ApplyItem = {
  id: number;
  title: string;
  organization_id: number | null;
  organization_name: string | null;
  location: string | null;
  date_discovered: string | null;
  fit_score: number | null;
  // Backend now includes both `interested` (queued) and `in_progress`
  // (started but not confirmed). in_progress rows sort first because
  // they're loose-ended work.
  status: "interested" | "in_progress";
};

type ApplyQueueOut = {
  total: number;
  ids: number[];
  items: ApplyItem[];
};

export function ApplyPanel() {
  const [data, setData] = useState<ApplyQueueOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // Persisted + shared with the review panel and the detail page's
  // "Next →" nav, so the whole flow agrees on skipping unscored jobs.
  const [scoredOnly, setScoredOnlyState] = useState(getScoredOnly);

  function toggleScoredOnly(v: boolean) {
    setScoredOnlyState(v);
    setScoredOnly(v);
  }

  useEffect(() => {
    setLoading(true);
    api
      .get<ApplyQueueOut>(
        `/api/v1/jobs/apply-queue${scoredOnly ? "?scored_only=true" : ""}`,
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

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const firstId = data?.ids?.[0];
  const inProgressCount = items.filter((it) => it.status === "in_progress").length;
  const interestedCount = items.filter((it) => it.status === "interested").length;

  const subtitle = (() => {
    if (total === 0) {
      return scoredOnly
        ? "No scored jobs queued to apply. Un-check the filter to see unscored ones."
        : "Nothing queued — mark jobs as 'interested' in the review queue to stack them here.";
    }
    const parts: string[] = [];
    if (inProgressCount > 0) {
      parts.push(
        `${inProgressCount} in progress — finish these first`,
      );
    }
    if (interestedCount > 0) {
      parts.push(
        `${interestedCount} queued to apply`,
      );
    }
    return parts.join(" · ") + ". Work through them with the apply-flow buttons on each detail page.";
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
              ? "No scored jobs waiting to apply to."
              : 'No jobs waiting to apply to. Triage the Review tab first or mark existing rows "interested" on the tracker.'}
          </p>
        </div>
      ) : (
        <ul className="jsp-card divide-y divide-corp-border overflow-hidden">
          {items.map((it, i) => {
            const inProgress = it.status === "in_progress";
            return (
              <li
                key={it.id}
                className="flex items-center gap-3 py-2 px-4 hover:bg-corp-surface2"
              >
                <span className="text-xs text-corp-muted w-8 text-right shrink-0">
                  #{i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate flex items-center gap-2">
                    <Link
                      href={`/jobs/${it.id}?from=apply`}
                      className="hover:text-corp-accent truncate"
                    >
                      {it.title}
                    </Link>
                    {inProgress ? (
                      <span
                        className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-full border border-amber-500/50 bg-amber-500/15 text-amber-300 shrink-0"
                        title="You clicked Apply on this one but haven't confirmed Applied / Not interested yet. Pick up where you left off."
                      >
                        In progress
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
                  href={`/jobs/${it.id}?from=apply`}
                  className="jsp-btn-ghost text-xs shrink-0"
                >
                  {inProgress ? "Resume →" : "Open →"}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
