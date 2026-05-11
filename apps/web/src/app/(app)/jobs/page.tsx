"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  downloadExcelTemplate,
  downloadQueueTemplate,
  FetchQueuePanel,
  importExcel,
  importQueueExcel,
} from "@/components/FetchQueuePanel";
import { InlineStatusPicker } from "@/components/InlineStatusPicker";
import { OrganizationCombobox } from "@/components/OrganizationCombobox";
import { PageShell } from "@/components/PageShell";
import { Paginator, usePagination } from "@/components/Paginator";
import { SkillsAnalysis } from "@/components/SkillsAnalysis";
import { StatusBadge, STATUS_STYLES } from "@/components/StatusBadge";
import { api, ApiError } from "@/lib/api";
import {
  EDUCATION_REQUIRED,
  EMPLOYMENT_TYPES,
  EXPERIENCE_LEVELS,
  JOB_STATUSES,
  type EducationRequired,
  type EmploymentType,
  type ExperienceLevel,
  type FetchedJobInfo,
  type JobStatus,
  type Priority,
  type RemotePolicy,
  type TrackedJob,
  type TrackedJobSummary,
} from "@/lib/types";

// Terminal / negative statuses hidden from the tracker list by default.
// Rejection and withdrawal rows are clutter once the user has moved on —
// they stay in the DB and re-appear when "Show closed/rejected" is on.
const NEGATIVE_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  "not_interested",
  "lost",
  "withdrawn",
  "ghosted",
  "archived",
]);

export default function JobTrackerPage() {
  const [items, setItems] = useState<TrackedJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "">("");
  const [showNegative, setShowNegative] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem("jsp:jobs:show_closed") === "1";
  });
  const [creating, setCreating] = useState(false);
  // Free-text search — applied client-side so the backend doesn't have to
  // implement full-text. Matches title, organization name, location, notes.
  const [search, setSearch] = useState("");
  // Multi-select on the tracker table. Selection survives filter-pill
  // switches (so the user can stage a bulk action across statuses) but
  // resets when a bulk action completes or Clear is clicked.
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [bulkStatusTarget, setBulkStatusTarget] = useState<JobStatus | "">("");
  // User's job preferences — hydrated lazily for the salary + location
  // badges. We only need a small subset, so the failure case is fine
  // (badges just don't render).
  const [prefs, setPrefs] = useState<{
    salary_acceptable_min?: number | null;
    salary_preferred_target?: number | null;
    salary_currency?: string | null;
    willing_to_relocate?: boolean;
    preferred_locations?: { name: string; max_distance_miles: number | null }[] | null;
    remote_policies_acceptable?: string[] | null;
  } | null>(null);
  useEffect(() => {
    api
      .get<typeof prefs>("/api/v1/preferences/job")
      .then((p) => setPrefs(p ?? {}))
      .catch(() => setPrefs({}));
  }, []);

  function toggleShowNegative(next: boolean) {
    setShowNegative(next);
    try {
      window.localStorage.setItem(
        "jsp:jobs:show_closed",
        next ? "1" : "0",
      );
    } catch {
      /* SSR / storage blocked — non-fatal */
    }
  }

  async function refresh() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      const data = await api.get<TrackedJobSummary[]>(
        `/api/v1/jobs?${params.toString()}`,
      );
      // Hide negative-connotation statuses unless the user has explicitly
      // filtered to one of them or flipped the "show closed" toggle on.
      // Filtering client-side so the backend stays simple and the same
      // shape works for the dashboard too.
      const visible =
        showNegative ||
        (statusFilter && NEGATIVE_STATUSES.has(statusFilter as JobStatus))
          ? data
          : data.filter((j) => !NEGATIVE_STATUSES.has(j.status));
      setItems(visible);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, showNegative]);

  // Sort key for the tracker table. "none" keeps the backend's
  // updated_at-desc ordering; "skill_match_pct" is the heatmap sort the
  // user can toggle from the Skills column header. The persisted-state
  // here is intentionally session-only — refreshing the page resets to
  // the natural recency order.
  const [sortKey, setSortKey] = useState<"none" | "skill_match_pct">("none");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Apply the search filter on top of whatever the backend returned.
  // Matches case-insensitively across title / org / location.
  // (TrackedJobSummary doesn't carry notes — that's full TrackedJob only.)
  const visibleItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    let arr = q
      ? items.filter((j) => {
          if (j.title?.toLowerCase().includes(q)) return true;
          if (j.organization_name?.toLowerCase().includes(q)) return true;
          if (j.location?.toLowerCase().includes(q)) return true;
          return false;
        })
      : items;
    if (sortKey === "skill_match_pct") {
      arr = [...arr].sort((a, b) => {
        const av = a.skill_match_pct;
        const bv = b.skill_match_pct;
        // Push nulls to the bottom regardless of direction so they don't
        // dominate the top of the list with "no analysis yet".
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        return sortDir === "desc" ? bv - av : av - bv;
      });
    }
    return arr;
  }, [items, search, sortKey, sortDir]);

  // Pagination layered on top of filter+search+sort. Page-size choice
  // persists per-page via localStorage (jsp:paginate:jobs). The
  // header checkbox + bulk actions deliberately operate on the
  // current page only, so a user-visible "select all visible" matches
  // what they actually see.
  const pager = usePagination(visibleItems, "jobs");
  const pagedItems = pager.visibleItems;

  // Status counts across the full set (unfiltered). Quick-nav to each bucket.
  const [counts, setCounts] = useState<Partial<Record<JobStatus, number>>>({});
  useEffect(() => {
    api
      .get<TrackedJobSummary[]>("/api/v1/jobs")
      .then((all) => {
        const c: Partial<Record<JobStatus, number>> = {};
        for (const j of all) c[j.status] = (c[j.status] ?? 0) + 1;
        setCounts(c);
      })
      .catch(() => {});
  }, [items.length]);

  const fileInput = useRef<HTMLInputElement>(null);
  const queueFileInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [queueImporting, setQueueImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<
    { kind: "ok" | "warn" | "error"; text: string } | null
  >(null);

  async function onImport(file: File | null) {
    if (!file) return;
    setImporting(true);
    setImportMsg(null);
    try {
      const res = await importExcel(file);
      setImportMsg({
        kind: res.skipped_count === 0 ? "ok" : "warn",
        text: `Imported ${res.created_count} job${res.created_count === 1 ? "" : "s"}${
          res.skipped_count ? `, skipped ${res.skipped_count} (see console for row errors)` : ""
        }.`,
      });
      if (res.errors.length > 0) {
        // eslint-disable-next-line no-console
        console.warn("Excel import row errors:", res.errors);
      }
      refresh();
    } catch (err) {
      setImportMsg({
        kind: "error",
        text: err instanceof Error ? err.message : "Import failed.",
      });
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function toggleSelected(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setBulkMsg(null);
  }

  function toggleSelectAllVisible(visibleIds: number[]) {
    setSelectedIds((prev) => {
      // If every visible row is currently selected → clear the visible set.
      // Otherwise → add every visible row.
      const every = visibleIds.every((id) => prev.has(id));
      const next = new Set(prev);
      if (every) {
        for (const id of visibleIds) next.delete(id);
      } else {
        for (const id of visibleIds) next.add(id);
      }
      return next;
    });
    setBulkMsg(null);
  }

  async function bulkChangeStatus(target: JobStatus) {
    const ids = [...selectedIds];
    if (ids.length === 0 || !target) return;
    setBulkRunning(true);
    setBulkMsg(null);
    const results = await Promise.allSettled(
      ids.map((id) =>
        api.put(`/api/v1/jobs/${id}`, { status: target }),
      ),
    );
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const fail = results.length - ok;
    setBulkRunning(false);
    setBulkStatusTarget("");
    setSelectedIds(new Set());
    setBulkMsg(
      fail === 0
        ? `Updated ${ok} job${ok === 1 ? "" : "s"} to "${target}".`
        : `Updated ${ok} of ${results.length}; ${fail} failed.`,
    );
    setTimeout(() => setBulkMsg(null), 12000);
    await refresh();
  }

  /**
   * Fire a tailor POST for every selected job × every doc_type in
   * `docTypes`. The backend returns immediately with a placeholder
   * `GeneratedDocument`, so we can parallelize safely — the heavy
   * Claude work happens in the task queue. Counts successes and
   * failures; one bad row (e.g. missing JD) doesn't stop the rest.
   */
  async function bulkTailor(docTypes: ("resume" | "cover_letter")[]) {
    const ids = [...selectedIds];
    if (ids.length === 0 || docTypes.length === 0) return;
    setBulkRunning(true);
    setBulkMsg(null);
    const results = await Promise.allSettled(
      ids.flatMap((id) =>
        docTypes.map((doc_type) =>
          api.post<{ id: number }>(`/api/v1/documents/tailor/${id}`, {
            doc_type,
          }),
        ),
      ),
    );
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const fail = results.length - ok;
    setBulkRunning(false);
    setSelectedIds(new Set());
    const kinds = docTypes
      .map((t) => (t === "cover_letter" ? "cover letter" : t))
      .join(" + ");
    setBulkMsg(
      fail === 0
        ? `Queued ${ok} ${kinds} task${ok === 1 ? "" : "s"} for ${ids.length} job${ids.length === 1 ? "" : "s"}. Watch the Companion Activity page for progress.`
        : `Queued ${ok} of ${results.length} (${fail} failed — usually missing job descriptions). Check /queue.`,
    );
    setTimeout(() => setBulkMsg(null), 15000);
  }

  async function onQueueImport(file: File | null) {
    if (!file) return;
    setQueueImporting(true);
    setImportMsg(null);
    try {
      const res = await importQueueExcel(file);
      setImportMsg({
        kind: res.skipped_count === 0 ? "ok" : "warn",
        text: `Enqueued ${res.enqueued_count} URL${res.enqueued_count === 1 ? "" : "s"} — the Companion will fetch them in the background${
          res.skipped_count
            ? `, skipped ${res.skipped_count} (see console for row errors)`
            : ""
        }.`,
      });
      if (res.errors.length > 0) {
        // eslint-disable-next-line no-console
        console.warn("Queue import row errors:", res.errors);
      }
      // No refresh() — the queue panel polls on its own.
    } catch (err) {
      setImportMsg({
        kind: "error",
        text: err instanceof Error ? err.message : "Queue import failed.",
      });
    } finally {
      setQueueImporting(false);
      if (queueFileInput.current) queueFileInput.current.value = "";
    }
  }

  return (
    <PageShell
      title="Job Tracker"
      subtitle="Every opportunity, from the first sighting through offer or — let's be honest — ghosting."
      actions={
        <div className="flex gap-2 items-center">
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => downloadExcelTemplate()}
            title="Download a pre-formatted Excel template for bulk import"
          >
            Excel template
          </button>
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => fileInput.current?.click()}
            disabled={importing}
          >
            {importing ? "Importing..." : "Import Excel"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => onImport(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => downloadQueueTemplate()}
            title="Download the minimal queue-import template: URL + optional dates"
          >
            Queue template
          </button>
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => queueFileInput.current?.click()}
            disabled={queueImporting}
            title="Import a list of URLs into the fetch queue — Companion visits each one"
          >
            {queueImporting ? "Importing..." : "Import queue"}
          </button>
          <input
            ref={queueFileInput}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => onQueueImport(e.target.files?.[0] ?? null)}
          />
          <ScoreAllButton onDone={refresh} />
          <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
            + New Job
          </button>
        </div>
      }
    >
      {importMsg ? (
        <div
          className={
            "jsp-card p-3 mb-3 text-sm " +
            (importMsg.kind === "ok"
              ? "text-corp-ok border-l-4 border-l-corp-ok"
              : importMsg.kind === "warn"
                ? "text-corp-accent2 border-l-4 border-l-corp-accent2"
                : "text-corp-danger border-l-4 border-l-corp-danger")
          }
        >
          {importMsg.text}
        </div>
      ) : null}

      <div className="mb-3">
        <FetchQueuePanel onJobCreated={refresh} />
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <StatusFilterPills
          current={statusFilter}
          counts={counts}
          onChange={setStatusFilter}
          showNegative={showNegative}
        />
        <label
          className="inline-flex items-center gap-1.5 text-[11px] text-corp-muted cursor-pointer select-none ml-auto"
          title={
            "Hidden by default: not_interested, lost, withdrawn, ghosted, " +
            "archived. They're still in the DB; flip this on to show them."
          }
        >
          <input
            type="checkbox"
            className="accent-corp-accent"
            checked={showNegative}
            onChange={(e) => toggleShowNegative(e.target.checked)}
          />
          Show closed / rejected
        </label>
        <RecomputeFitButton onDone={() => refresh()} />
        <AutoArchiveButton onArchived={() => refresh()} />
      </div>

      {creating ? (
        <div className="jsp-card p-4 mb-4 mt-4">
          <NewJobForm
            onCancel={() => setCreating(false)}
            onSaved={(created) => {
              setCreating(false);
              refresh();
              // bounce into detail for immediate editing
              window.location.href = `/jobs/${created.id}`;
            }}
          />
        </div>
      ) : null}

      {bulkMsg ? (
        <div className="jsp-card p-3 mt-3 text-xs text-corp-muted border-l-4 border-l-corp-accent">
          {bulkMsg}
        </div>
      ) : null}

      {selectedIds.size > 0 ? (
        <div className="jsp-card p-3 mt-3 flex flex-wrap gap-3 items-center border-l-4 border-l-corp-accent">
          <span className="text-sm">
            <strong>{selectedIds.size}</strong> selected
          </span>

          {/* Status group — labeled + accent-bordered so it reads as
              a primary bulk action, not a buried form field. */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded border border-corp-accent/40 bg-corp-accent/10">
            <span className="text-[10px] uppercase tracking-wider text-corp-accent">
              Status
            </span>
            <select
              className="jsp-input text-xs py-0.5 w-40 bg-corp-surface"
              value={bulkStatusTarget}
              onChange={(e) => {
                const v = e.target.value as JobStatus | "";
                setBulkStatusTarget(v);
                if (v) bulkChangeStatus(v);
              }}
              disabled={bulkRunning}
              title="Apply this status to every selected job"
              aria-label="Change status of selected jobs"
            >
              <option value="">— pick a status —</option>
              {JOB_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>

          {/* Tailor group — separated visually from the status control
              so neither feels lumped in with the other. */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded border border-corp-border">
            <span className="text-[10px] uppercase tracking-wider text-corp-muted">
              Tailor
            </span>
            <button
              type="button"
              className="jsp-btn-ghost text-xs"
              onClick={() => bulkTailor(["resume"])}
              disabled={bulkRunning}
              title="Queue a tailor run for each selected job — writes a resume per job"
            >
              Resumes
            </button>
            <button
              type="button"
              className="jsp-btn-ghost text-xs"
              onClick={() => bulkTailor(["cover_letter"])}
              disabled={bulkRunning}
              title="Queue a tailor run for each selected job — writes a cover letter per job"
            >
              Cover letters
            </button>
            <button
              type="button"
              className="jsp-btn-primary text-xs"
              onClick={() => bulkTailor(["resume", "cover_letter"])}
              disabled={bulkRunning}
              title="Queue both a resume and a cover letter per selected job"
            >
              {bulkRunning ? "Queuing…" : "Both"}
            </button>
          </div>

          <button
            type="button"
            className="jsp-btn-ghost text-xs ml-auto"
            onClick={() => {
              setSelectedIds(new Set());
              setBulkMsg(null);
            }}
            disabled={bulkRunning}
          >
            Clear selection
          </button>
        </div>
      ) : null}

      <div className="mt-3 mb-2">
        <input
          type="text"
          className="jsp-input"
          placeholder="Search jobs by title, organization, or location…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <p className="text-corp-muted mt-4">Loading...</p>
      ) : visibleItems.length === 0 ? (
        <div className="jsp-card p-6 text-corp-muted text-sm mt-4">
          {search.trim()
            ? `No jobs match "${search.trim()}".`
            : statusFilter
              ? `No jobs with status "${statusFilter}".`
              : "No jobs tracked yet. Add one above — paste a URL, a title, and Claude will fill in the rest as you go."}
        </div>
      ) : (
        <div className="jsp-card mt-4 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-corp-surface2 text-left text-[11px] uppercase tracking-wider text-corp-muted">
                <th className="py-2 px-2 w-8">
                  <input
                    type="checkbox"
                    className="accent-corp-accent"
                    aria-label="Select all rows on this page"
                    checked={
                      pagedItems.length > 0 &&
                      pagedItems.every((j) => selectedIds.has(j.id))
                    }
                    // Indeterminate state when some but not all current-page
                    // rows are selected — React doesn't expose it as a prop,
                    // so set via ref on the DOM element.
                    ref={(el) => {
                      if (el) {
                        const count = pagedItems.filter((j) =>
                          selectedIds.has(j.id),
                        ).length;
                        el.indeterminate =
                          count > 0 && count < pagedItems.length;
                      }
                    }}
                    onChange={() =>
                      toggleSelectAllVisible(pagedItems.map((j) => j.id))
                    }
                    onClick={(e) => e.stopPropagation()}
                  />
                </th>
                <th className="py-2 px-4">Title</th>
                <th className="py-2 px-4">Organization</th>
                <th className="py-2 px-4">Status</th>
                <th className="py-2 px-4">Fit</th>
                <th
                  className="py-2 px-4 cursor-pointer select-none hover:text-corp-text"
                  onClick={() => {
                    if (sortKey !== "skill_match_pct") {
                      setSortKey("skill_match_pct");
                      setSortDir("desc");
                    } else if (sortDir === "desc") {
                      setSortDir("asc");
                    } else {
                      setSortKey("none");
                    }
                  }}
                  title="Sort by % of required skills matched. Click again to flip, again to clear."
                >
                  Skills
                  {sortKey === "skill_match_pct" ? (
                    <span className="ml-1 text-corp-accent">
                      {sortDir === "desc" ? "↓" : "↑"}
                    </span>
                  ) : null}
                </th>
                <th className="py-2 px-4">Rounds</th>
                <th className="py-2 px-4">Applied</th>
                <th className="py-2 px-4 text-right">Updated</th>
              </tr>
            </thead>
            <tbody>
              {pagedItems.map((j) => (
                <tr
                  key={j.id}
                  className={`border-t border-corp-border hover:bg-corp-surface2 cursor-pointer ${
                    selectedIds.has(j.id) ? "bg-corp-accent/10" : ""
                  }`}
                  onClick={() => (window.location.href = `/jobs/${j.id}`)}
                >
                  <td
                    className="py-2 px-2 w-8"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      className="accent-corp-accent"
                      checked={selectedIds.has(j.id)}
                      onChange={() => toggleSelected(j.id)}
                      aria-label={`Select ${j.title}`}
                    />
                  </td>
                  <td className="py-2 px-4">
                    <Link href={`/jobs/${j.id}`} className="hover:text-corp-accent">
                      {j.title}
                    </Link>
                    {j.location || j.remote_policy ? (
                      <div className="text-[11px] text-corp-muted mt-0.5">
                        {[j.location, j.remote_policy].filter(Boolean).join(" · ")}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-2 px-4 text-corp-muted">
                    {j.organization_name ?? "—"}
                  </td>
                  <td className="py-2 px-4">
                    <InlineStatusPicker
                      jobId={j.id}
                      status={j.status}
                      onChange={(next) =>
                        setItems((prev) =>
                          prev.map((row) =>
                            row.id === j.id ? { ...row, status: next } : row,
                          ),
                        )
                      }
                    />
                  </td>
                  <td className="py-2 px-4">
                    <div className="flex flex-wrap gap-1 items-center">
                      <FitPill
                        score={j.fit_score ?? null}
                        redFlagCount={j.red_flag_count ?? 0}
                      />
                      <SalaryBadge job={j} prefs={prefs} />
                      <LocationFitBadge job={j} prefs={prefs} />
                    </div>
                  </td>
                  <td className="py-2 px-4">
                    <SkillMatchHeatmap
                      pct={j.skill_match_pct ?? null}
                      have={j.skill_match_have ?? null}
                      total={j.skill_match_total ?? null}
                    />
                  </td>
                  <td className="py-2 px-4 text-corp-muted">
                    {j.rounds_count}
                    {j.latest_round_outcome && j.latest_round_outcome !== "pending" ? (
                      <span className="ml-1 text-[10px] uppercase tracking-wider">
                        · {j.latest_round_outcome}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2 px-4 text-corp-muted">
                    {j.date_applied ?? "—"}
                  </td>
                  <td className="py-2 px-4 text-right text-[11px] text-corp-muted">
                    {new Date(j.updated_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Paginator
            page={pager.page}
            pageSize={pager.pageSize}
            setPage={pager.setPage}
            setPageSize={pager.setPageSize}
            total={pager.total}
            totalPages={pager.totalPages}
            className="px-4 py-2 border-t border-corp-border"
          />
        </div>
      )}
    </PageShell>
  );
}

/** Render a green/amber/red salary badge derived from the job's posted
 * range vs. the user's preferences. Returns null when there's nothing
 * to compare (no posted range or no preferences yet). */
function SalaryBadge({
  job,
  prefs,
}: {
  job: TrackedJobSummary;
  prefs: {
    salary_acceptable_min?: number | null;
    salary_preferred_target?: number | null;
  } | null;
}) {
  if (!prefs) return null;
  const min = job.salary_min ?? null;
  const max = job.salary_max ?? null;
  if (min == null && max == null) return null;
  const accept = prefs.salary_acceptable_min ?? null;
  const target = prefs.salary_preferred_target ?? null;
  const ceiling = max ?? min;
  const floor = min ?? max;
  if (ceiling == null || floor == null) return null;
  let tone: "good" | "warn" | "danger" = "warn";
  let label = "salary";
  if (accept != null && ceiling < accept) {
    tone = "danger";
    label = "below acceptable";
  } else if (target != null && ceiling >= target) {
    tone = "good";
    label = "≥ target";
  } else if (accept != null && floor >= accept) {
    tone = "good";
    label = "in range";
  } else {
    tone = "warn";
    label = "below preferred";
  }
  const tone_class =
    tone === "good"
      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
      : tone === "danger"
        ? "bg-corp-danger/20 text-corp-danger border-corp-danger/40"
        : "bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40";
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border ${tone_class}`}
      title={`Listed ${min ?? "?"}–${max ?? "?"} vs. preferred target ${target ?? "?"} / acceptable min ${accept ?? "?"}`}
    >
      💰 {label}
    </span>
  );
}

/** Location-fit badge derived from `preferred_locations` + remote policy.
 * Naive substring match on city name (no geocoding). Returns null if
 * there's nothing useful to say. */
function LocationFitBadge({
  job,
  prefs,
}: {
  job: TrackedJobSummary;
  prefs: {
    willing_to_relocate?: boolean;
    preferred_locations?: { name: string; max_distance_miles: number | null }[] | null;
    remote_policies_acceptable?: string[] | null;
  } | null;
}) {
  if (!prefs) return null;
  const remote = job.remote_policy ?? null;
  const loc = (job.location ?? "").trim();
  // Remote-friendly job + user accepts remote → green and we're done.
  if (remote && (prefs.remote_policies_acceptable ?? []).includes(remote)) {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border bg-emerald-500/20 text-emerald-300 border-emerald-500/40">
        🏠 remote ok
      </span>
    );
  }
  if (!loc) return null;
  const locLower = loc.toLowerCase();
  const prefList = prefs.preferred_locations ?? [];
  // Substring match in either direction so "Seattle, WA" matches "Seattle".
  const hit = prefList.find((p) => {
    const a = p.name.toLowerCase();
    return a && (locLower.includes(a) || a.includes(locLower));
  });
  if (hit) {
    const radius = hit.max_distance_miles
      ? `${hit.max_distance_miles} mi of ${hit.name}`
      : hit.name;
    return (
      <span
        className="inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
        title={`Within preferred radius — ${radius}`}
      >
        📍 fit
      </span>
    );
  }
  if (prefs.willing_to_relocate) {
    return (
      <span
        className="inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40"
        title="Outside any preferred location, but you marked yourself open to relocating"
      >
        📍 relocate
      </span>
    );
  }
  if (prefList.length === 0) return null;
  return (
    <span
      className="inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border bg-corp-danger/20 text-corp-danger border-corp-danger/40"
      title={`Posting at ${loc} doesn't match any of your preferred_locations`}
    >
      📍 outside
    </span>
  );
}


/** Skill-match heatmap cell — a thin colored bar plus "have/total"
 * caption. Renders an em-dash when the JD didn't surface required_skills
 * (no analysis yet) so the column doesn't lie about a 0% match. */
function SkillMatchHeatmap({
  pct,
  have,
  total,
}: {
  pct: number | null;
  have: number | null;
  total: number | null;
}) {
  if (pct == null || total == null || total === 0) {
    return <span className="text-corp-muted text-[11px]">—</span>;
  }
  const tone =
    pct >= 75
      ? "bg-emerald-500"
      : pct >= 50
        ? "bg-corp-accent"
        : pct >= 25
          ? "bg-corp-accent2"
          : "bg-corp-danger";
  return (
    <div
      className="flex flex-col gap-1"
      title={`${have ?? 0} of ${total} required skills matched`}
    >
      <div className="h-1.5 w-16 rounded bg-corp-surface2 overflow-hidden border border-corp-border">
        <div
          className={`h-full ${tone}`}
          style={{ width: `${Math.max(2, Math.min(100, pct))}%` }}
        />
      </div>
      <span className="text-[10px] text-corp-muted">
        {pct}% · {have}/{total}
      </span>
    </div>
  );
}


/** Run the auto-archive sweep. Shows a preview confirmation first so
 * the user always sees what's about to move; clicking through actually
 * archives the rows. Inert when there's nothing stale. */
/** Re-run the deterministic fit-score across every tracked job. Cheap
 * (pure-Python) so we can offer a one-click button instead of a queue
 * task. Used after the user changes preferences / criteria / weights. */
function RecomputeFitButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setMsg(null);
    try {
      const out = await api.post<{
        rescored: number;
        vetoed: number;
        unknown: number;
      }>("/api/v1/jobs/recompute-fit-score-all", {});
      setMsg(
        `${out.rescored} rescored · ${out.vetoed} vetoed · ${out.unknown} unscored.`,
      );
      onDone();
      setTimeout(() => setMsg(null), 4000);
    } catch (e) {
      setMsg(
        e instanceof ApiError
          ? `Recompute failed (HTTP ${e.status}).`
          : "Recompute failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        className="jsp-btn-ghost text-xs"
        onClick={run}
        disabled={busy}
        title="Recompute the deterministic fit score for every tracked job using your current preferences + criteria + weights."
      >
        {busy ? "Recomputing…" : "Recompute fit"}
      </button>
      {msg ? (
        <span className="text-[11px] text-corp-muted">{msg}</span>
      ) : null}
    </span>
  );
}


function AutoArchiveButton({ onArchived }: { onArchived: () => void }) {
  const [busy, setBusy] = useState<"idle" | "preview" | "running">("idle");
  const [preview, setPreview] = useState<{
    candidates_by_bucket: Record<string, number>;
    total: number;
    sample_titles: string[];
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function loadPreview() {
    setErr(null);
    setBusy("preview");
    try {
      const p = await api.get<{
        candidates_by_bucket: Record<string, number>;
        total: number;
        sample_titles: string[];
      }>("/api/v1/jobs/auto-archive/preview");
      setPreview(p);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Preview failed (HTTP ${e.status}).`
          : "Preview failed.",
      );
    } finally {
      setBusy("idle");
    }
  }

  async function execute() {
    setErr(null);
    setBusy("running");
    try {
      const out = await api.post<{ archived: number }>(
        "/api/v1/jobs/auto-archive",
        {},
      );
      setPreview(null);
      onArchived();
      alert(`Archived ${out.archived} stale job${out.archived === 1 ? "" : "s"}.`);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Archive failed (HTTP ${e.status}).`
          : "Archive failed.",
      );
    } finally {
      setBusy("idle");
    }
  }

  if (preview) {
    return (
      <div className="jsp-card p-3 ml-2 max-w-sm text-[11px]">
        <div className="font-medium mb-1">
          Auto-archive: {preview.total} job{preview.total === 1 ? "" : "s"}
        </div>
        {preview.total > 0 ? (
          <>
            <ul className="space-y-0.5 text-corp-muted">
              {Object.entries(preview.candidates_by_bucket).map(
                ([k, n]) =>
                  n > 0 ? (
                    <li key={k}>
                      {k}: <span className="text-corp-text">{n}</span>
                    </li>
                  ) : null,
              )}
            </ul>
            {preview.sample_titles.length > 0 ? (
              <div className="mt-1 text-corp-muted truncate">
                e.g. {preview.sample_titles.slice(0, 3).join(", ")}
                {preview.sample_titles.length > 3 ? "…" : ""}
              </div>
            ) : null}
          </>
        ) : (
          <div className="text-corp-muted">
            Nothing stale right now — every job is recent.
          </div>
        )}
        <div className="flex gap-1.5 mt-2 justify-end">
          <button
            type="button"
            className="jsp-btn-ghost text-xs"
            onClick={() => setPreview(null)}
          >
            Cancel
          </button>
          {preview.total > 0 ? (
            <button
              type="button"
              className="jsp-btn-primary text-xs"
              onClick={execute}
              disabled={busy === "running"}
            >
              {busy === "running" ? "…" : "Archive"}
            </button>
          ) : null}
        </div>
        {err ? <div className="text-corp-danger mt-1">{err}</div> : null}
      </div>
    );
  }

  return (
    <button
      type="button"
      className="jsp-btn-ghost text-xs"
      onClick={loadPreview}
      disabled={busy !== "idle"}
      title={
        "Move stale rows to status=archived: pre-application ≥60 days, " +
        "in-flight ≥90 days, ghosted/lost/withdrawn ≥30 days. " +
        "Always shows a preview first."
      }
    >
      {busy === "preview" ? "…" : "Auto-archive stale"}
    </button>
  );
}


function StatusFilterPills({
  current,
  counts,
  onChange,
  showNegative,
}: {
  current: JobStatus | "";
  counts: Partial<Record<JobStatus, number>>;
  onChange: (s: JobStatus | "") => void;
  showNegative: boolean;
}) {
  const visible = useMemo(
    () =>
      JOB_STATUSES.filter((s) => {
        // Always show a pill if it's the current filter so the user sees
        // what's active even if counts update or the toggle flips.
        if (s === current) return true;
        // Otherwise require at least one matching job AND — for negative
        // statuses — an explicit opt-in via the "Show closed" toggle.
        if ((counts[s] ?? 0) === 0) return false;
        if (!showNegative && NEGATIVE_STATUSES.has(s)) return false;
        return true;
      }),
    [counts, current, showNegative],
  );

  return (
    <div className="flex flex-wrap gap-1.5 items-center">
      <button
        className={`px-2.5 py-1 rounded-md text-xs uppercase tracking-wider border ${
          current === ""
            ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
            : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text"
        }`}
        onClick={() => onChange("")}
      >
        All
      </button>
      {visible.map((s) => (
        <button
          key={s}
          onClick={() => onChange(current === s ? "" : s)}
          className={`px-2.5 py-1 rounded-md text-xs uppercase tracking-wider border transition-opacity ${
            STATUS_STYLES[s]
          } ${current && current !== s ? "opacity-40" : ""}`}
        >
          {s}
          {counts[s] ? (
            <span className="ml-1 opacity-70">{counts[s]}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

// ---------- New job form -----------------------------------------------------

function NewJobForm({
  onCancel,
  onSaved,
}: {
  onCancel: () => void;
  onSaved: (job: TrackedJob) => void;
}) {
  const [title, setTitle] = useState("");
  const [organizationId, setOrganizationId] = useState<number | null>(null);
  // Bump this key to force the OrganizationCombobox to re-read its `value`
  // prop after a URL fetch updates the organization_id externally.
  const [orgPickerKey, setOrgPickerKey] = useState(0);
  const [status, setStatus] = useState<JobStatus>("to_review");
  const [sourceUrl, setSourceUrl] = useState("");
  const [location, setLocation] = useState("");
  const [remotePolicy, setRemotePolicy] = useState<RemotePolicy | "">("");
  const [priority, setPriority] = useState<Priority | "">("");
  const [jd, setJd] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const [dateApplied, setDateApplied] = useState("");
  const [dateClosed, setDateClosed] = useState("");

  // JD-extracted fields
  const [datePosted, setDatePosted] = useState("");
  const [salaryMin, setSalaryMin] = useState<string>("");
  const [salaryMax, setSalaryMax] = useState<string>("");
  const [salaryCurrency, setSalaryCurrency] = useState("");
  const [expYearsMin, setExpYearsMin] = useState<string>("");
  const [expYearsMax, setExpYearsMax] = useState<string>("");
  const [experienceLevel, setExperienceLevel] = useState<ExperienceLevel | "">("");
  const [employmentType, setEmploymentType] = useState<EmploymentType | "">("");
  const [educationRequired, setEducationRequired] = useState<EducationRequired | "">("");
  const [visaSponsorship, setVisaSponsorship] = useState<"yes" | "no" | "">("");
  const [relocation, setRelocation] = useState<"yes" | "no" | "">("");
  const [requiredSkills, setRequiredSkills] = useState<string[] | null>(null);
  const [niceToHave, setNiceToHave] = useState<string[] | null>(null);

  // Fetch-from-URL state
  const [fetchUrl, setFetchUrl] = useState("");
  const [fetching, setFetching] = useState(false);
  const [fetchMsg, setFetchMsg] = useState<{ kind: "ok" | "warn" | "error"; text: string } | null>(null);

  async function doFetch() {
    const url = fetchUrl.trim();
    if (!url) return;
    setFetching(true);
    setFetchMsg(null);
    try {
      const info = await api.post<FetchedJobInfo>("/api/v1/jobs/fetch-from-url", { url });
      // Populate each field only if the fetch actually provided a value; never
      // clobber what the user already typed.
      if (info.title && !title) setTitle(info.title);
      if (info.location && !location) setLocation(info.location);
      if (info.remote_policy && !remotePolicy) setRemotePolicy(info.remote_policy);
      if (info.job_description && !jd) setJd(info.job_description);
      if (info.source_url && !sourceUrl) setSourceUrl(info.source_url);
      if (info.date_posted && !datePosted) setDatePosted(info.date_posted);
      if (info.salary_min != null && !salaryMin) setSalaryMin(String(info.salary_min));
      if (info.salary_max != null && !salaryMax) setSalaryMax(String(info.salary_max));
      if (info.salary_currency && !salaryCurrency) setSalaryCurrency(info.salary_currency);
      if (info.experience_years_min != null && !expYearsMin)
        setExpYearsMin(String(info.experience_years_min));
      if (info.experience_years_max != null && !expYearsMax)
        setExpYearsMax(String(info.experience_years_max));
      if (info.experience_level && !experienceLevel)
        setExperienceLevel(info.experience_level);
      if (info.employment_type && !employmentType)
        setEmploymentType(info.employment_type);
      if (info.education_required && !educationRequired)
        setEducationRequired(info.education_required);
      if (info.visa_sponsorship_offered != null && !visaSponsorship)
        setVisaSponsorship(info.visa_sponsorship_offered ? "yes" : "no");
      if (info.relocation_offered != null && !relocation)
        setRelocation(info.relocation_offered ? "yes" : "no");
      setRequiredSkills(info.required_skills ?? null);
      setNiceToHave(info.nice_to_have_skills ?? null);

      // Backend resolves or creates the Organization itself and returns its id.
      if (info.organization_id && !organizationId) {
        setOrganizationId(info.organization_id);
        setOrgPickerKey((k) => k + 1);
      }

      if (info.warning) {
        setFetchMsg({ kind: "warn", text: info.warning });
      } else {
        const extras: string[] = [];
        if (info.organization_name) extras.push(info.organization_name);
        if (info.organization_industry) extras.push(info.organization_industry);
        if (info.organization_size) extras.push(info.organization_size);
        const researchLine = info.research_notes ? ` — ${info.research_notes}` : "";
        setFetchMsg({
          kind: "ok",
          text:
            `Prefilled from ${new URL(url).hostname}` +
            (extras.length ? ` (${extras.join(" · ")})` : "") +
            researchLine,
        });
      }
    } catch (err) {
      setFetchMsg({
        kind: "error",
        text:
          err instanceof ApiError
            ? `Fetch failed (HTTP ${err.status}). You can still fill the form manually.`
            : "Fetch failed. You can still fill the form manually.",
      });
    } finally {
      setFetching(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      const payload: Partial<TrackedJob> = {
        title,
        status,
        organization_id: organizationId,
        source_url: sourceUrl || null,
        location: location || null,
        remote_policy: (remotePolicy || null) as RemotePolicy | null,
        priority: (priority || null) as Priority | null,
        job_description: jd || null,
        notes: notes || null,
        date_posted: datePosted || null,
        date_applied: dateApplied || null,
        date_closed: dateClosed || null,
        salary_min: salaryMin ? Number(salaryMin) : null,
        salary_max: salaryMax ? Number(salaryMax) : null,
        salary_currency: salaryCurrency || null,
        experience_years_min: expYearsMin ? Number(expYearsMin) : null,
        experience_years_max: expYearsMax ? Number(expYearsMax) : null,
        experience_level: (experienceLevel || null) as ExperienceLevel | null,
        employment_type: (employmentType || null) as EmploymentType | null,
        education_required:
          (educationRequired || null) as EducationRequired | null,
        visa_sponsorship_offered:
          visaSponsorship === "" ? null : visaSponsorship === "yes",
        relocation_offered: relocation === "" ? null : relocation === "yes",
        required_skills: requiredSkills,
        nice_to_have_skills: niceToHave,
      };
      const created = await api.post<TrackedJob>("/api/v1/jobs", payload);
      onSaved(created);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="jsp-card p-3 border-l-4 border-l-corp-accent/60 space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs uppercase tracking-wider text-corp-muted">
            Fetch from URL
          </span>
          <span className="text-[10px] text-corp-muted">
            Paste a job posting link and the Companion will prefill what it can.
          </span>
        </div>
        <div className="flex gap-2">
          <input
            className="jsp-input flex-1 font-mono text-xs"
            placeholder="https://..."
            value={fetchUrl}
            onChange={(e) => setFetchUrl(e.target.value)}
            disabled={fetching}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                doFetch();
              }
            }}
          />
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={doFetch}
            disabled={fetching || !fetchUrl.trim()}
          >
            {fetching ? "Fetching..." : "Fetch"}
          </button>
        </div>
        {fetchMsg ? (
          <div
            className={
              fetchMsg.kind === "ok"
                ? "text-xs text-corp-ok"
                : fetchMsg.kind === "warn"
                  ? "text-xs text-corp-accent2"
                  : "text-xs text-corp-danger"
            }
          >
            {fetchMsg.text}
          </div>
        ) : null}
      </div>

      {(requiredSkills && requiredSkills.length > 0) ||
      (niceToHave && niceToHave.length > 0) ? (
        <SkillsAnalysis required={requiredSkills} niceToHave={niceToHave} />
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Title</label>
          <input
            className="jsp-input"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Senior Widget Engineer"
          />
        </div>
        <div>
          <label className="jsp-label">Organization</label>
          <OrganizationCombobox
            key={orgPickerKey}
            value={organizationId}
            onChange={setOrganizationId}
            defaultTypeOnCreate="company"
          />
        </div>
        <div>
          <label className="jsp-label">Status</label>
          <select
            className="jsp-input"
            value={status}
            onChange={(e) => setStatus(e.target.value as JobStatus)}
          >
            {JOB_STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Priority</label>
          <select
            className="jsp-input"
            value={priority}
            onChange={(e) => setPriority(e.target.value as Priority | "")}
          >
            <option value="">—</option>
            <option>low</option>
            <option>medium</option>
            <option>high</option>
          </select>
        </div>
        <div>
          <label className="jsp-label">Location</label>
          <input
            className="jsp-input"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Remote policy</label>
          <select
            className="jsp-input"
            value={remotePolicy}
            onChange={(e) => setRemotePolicy(e.target.value as RemotePolicy | "")}
          >
            <option value="">—</option>
            <option>onsite</option>
            <option>hybrid</option>
            <option>remote</option>
          </select>
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Source URL</label>
          <input
            className="jsp-input"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://…"
          />
        </div>
        <div>
          <label className="jsp-label">Date posted</label>
          <input
            type="date"
            className="jsp-input"
            value={datePosted}
            onChange={(e) => setDatePosted(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Date applied</label>
          <input
            type="date"
            className="jsp-input"
            value={dateApplied}
            onChange={(e) => setDateApplied(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Date closed</label>
          <input
            type="date"
            className="jsp-input"
            value={dateClosed}
            onChange={(e) => setDateClosed(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Employment type</label>
          <select
            className="jsp-input"
            value={employmentType}
            onChange={(e) =>
              setEmploymentType(e.target.value as EmploymentType | "")
            }
          >
            <option value="">—</option>
            {EMPLOYMENT_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Experience level</label>
          <select
            className="jsp-input"
            value={experienceLevel}
            onChange={(e) =>
              setExperienceLevel(e.target.value as ExperienceLevel | "")
            }
          >
            <option value="">—</option>
            {EXPERIENCE_LEVELS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Education required</label>
          <select
            className="jsp-input"
            value={educationRequired}
            onChange={(e) =>
              setEducationRequired(e.target.value as EducationRequired | "")
            }
          >
            <option value="">—</option>
            {EDUCATION_REQUIRED.map((e) => (
              <option key={e}>{e}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Years experience min</label>
          <input
            type="number"
            className="jsp-input"
            value={expYearsMin}
            onChange={(e) => setExpYearsMin(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Years experience max</label>
          <input
            type="number"
            className="jsp-input"
            value={expYearsMax}
            onChange={(e) => setExpYearsMax(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Salary min</label>
          <input
            type="number"
            className="jsp-input"
            value={salaryMin}
            onChange={(e) => setSalaryMin(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Salary max</label>
          <input
            type="number"
            className="jsp-input"
            value={salaryMax}
            onChange={(e) => setSalaryMax(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Currency</label>
          <input
            className="jsp-input"
            placeholder="USD"
            value={salaryCurrency}
            onChange={(e) => setSalaryCurrency(e.target.value.toUpperCase().slice(0, 8))}
          />
        </div>
        <div>
          <label className="jsp-label">Visa sponsorship</label>
          <select
            className="jsp-input"
            value={visaSponsorship}
            onChange={(e) => setVisaSponsorship(e.target.value as "" | "yes" | "no")}
          >
            <option value="">— (not stated)</option>
            <option value="yes">Offered</option>
            <option value="no">Not offered</option>
          </select>
        </div>
        <div>
          <label className="jsp-label">Relocation</label>
          <select
            className="jsp-input"
            value={relocation}
            onChange={(e) => setRelocation(e.target.value as "" | "yes" | "no")}
          >
            <option value="">— (not stated)</option>
            <option value="yes">Offered</option>
            <option value="no">Not offered</option>
          </select>
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Job description</label>
          <textarea
            className="jsp-input min-h-[160px] font-mono text-xs"
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            placeholder="Paste the JD here. Fetch from URL above will populate it verbatim."
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Notes</label>
          <textarea
            className="jsp-input min-h-[60px]"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving || !title.trim()}>
          {saving ? "..." : "Create"}
        </button>
      </div>
    </form>
  );
}

function ScoreAllButton({ onDone }: { onDone: () => void }) {
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setMsg(null);
    try {
      const r = await api.post<{
        enqueued: number;
        skipped_no_description: number;
        skipped_already_scored: number;
        errors?: { job_id: number; error: string }[];
      }>("/api/v1/jobs/batch-analyze-jd");
      let m = `Queued ${r.enqueued} for scoring`;
      if (r.skipped_already_scored)
        m += ` · ${r.skipped_already_scored} already scored`;
      if (r.skipped_no_description) m += ` · ${r.skipped_no_description} no JD`;
      if (r.enqueued > 0) m += " · see Companion Activity for progress";
      setMsg(m);
      onDone();
    } catch (e) {
      setMsg(
        e instanceof ApiError ? `Batch failed (HTTP ${e.status}).` : "Batch failed.",
      );
    } finally {
      setRunning(false);
      setTimeout(() => setMsg(null), 12000);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className="jsp-btn-ghost"
        onClick={run}
        disabled={running}
        title="Enqueue JD analysis for every unscored job — each appears on the Companion Activity page"
      >
        {running ? "Queuing..." : "Score all"}
      </button>
      {msg ? (
        <span className="text-[11px] text-corp-muted">{msg}</span>
      ) : null}
    </div>
  );
}

function FitPill({
  score,
  redFlagCount,
}: {
  score: number | null;
  redFlagCount: number;
}) {
  if (score === null || score === undefined) {
    return (
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-corp-muted">—</span>
        {redFlagCount > 0 ? (
          <span
            className="text-[11px] text-corp-danger"
            title={`${redFlagCount} red flag${redFlagCount === 1 ? "" : "s"} in JD analysis`}
          >
            ⚠{redFlagCount}
          </span>
        ) : null}
      </div>
    );
  }
  const tone =
    score >= 75
      ? "bg-emerald-500/25 text-emerald-300 border-emerald-500/40"
      : score >= 50
        ? "bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40"
        : "bg-corp-danger/20 text-corp-danger border-corp-danger/40";
  return (
    <div className="flex items-center gap-1">
      <span
        className={`inline-block px-2 py-0.5 rounded text-[11px] tabular-nums border ${tone}`}
        title="JD fit score — run the analyzer on the job detail page to update"
      >
        {score}
      </span>
      {redFlagCount > 0 ? (
        <span
          className="text-[11px] text-corp-danger"
          title={`${redFlagCount} red flag${redFlagCount === 1 ? "" : "s"}`}
        >
          ⚠{redFlagCount}
        </span>
      ) : null}
    </div>
  );
}
