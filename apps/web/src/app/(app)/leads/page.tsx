"use client";

// Job Leads inbox + Sources management.
//
// Two stacked panels: top is the registered Sources (add/edit/poll-now),
// bottom is the lead inbox with bulk-select → "Add to tracker" (which
// promotes to a tracked_jobs row at status=to_review and chains the
// fetch + score + research follow-on tasks) or Dismiss. Promotions
// always land at to_review so the review queue gates new rows before
// they inflate active-application counts.

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, apiUrl, ApiError } from "@/lib/api";
import { KeywordFilters, type KeywordFilter } from "./_panels/KeywordFilters";

type SourceKindExample = { label: string; value: string };

type SourceKind = {
  kind: string;
  label: string;
  hint: string;
  examples?: SourceKindExample[];
};

type Source = {
  id: number;
  kind: string;
  slug_or_url: string;
  label: string | null;
  enabled: boolean;
  filters: Record<string, unknown> | null;
  poll_interval_hours: number;
  lead_ttl_hours: number;
  max_leads_per_poll: number;
  last_polled_at: string | null;
  last_error: string | null;
  last_lead_count: number | null;
  new_lead_count: number | null;
  total_lead_count: number | null;
  created_at: string;
  updated_at: string;
};

type Lead = {
  id: number;
  source_id: number;
  source_kind: string | null;
  source_label: string | null;
  title: string;
  organization_name: string | null;
  location: string | null;
  remote_policy: string | null;
  source_url: string | null;
  description_md: string | null;
  posted_at: string | null;
  first_seen_at: string;
  expires_at: string;
  state: string;
  tracked_job_id: number | null;
  relevance_score: number | null;
  has_description?: boolean | null;
};

// One input row of a Bright Data keyword-discovery query — the same
// columns as the dataset's input CSV.
type BdInputRow = {
  location: string;
  keyword: string;
  country: string;
  time_range: string;
  job_type: string;
  experience_level: string;
  remote: string;
  company: string;
  location_radius: string;
};

const BD_KEYWORD_KIND = "brightdata_keyword";

// A Bright Data run was triggered and is still being collected by the
// background poller — normal for keyword discovery, not an error.
type RunSnapshot = {
  id: string | null;
  label: string;
  // queued (not sent yet) | retry (trigger failed, will retry) |
  // starting | running | ready | imported | failed
  status: string;
  attempts?: number;
  // Batched run: the searches this one Bright Data call covers.
  searches?: string[];
  leads: number;
  found?: number;
  auto_dismissed?: number;
  error: string | null;
};
type KeywordRun = {
  started_at: string;
  inserted: number;
  auto_dismissed?: number;
  snapshots: RunSnapshot[];
};
type LastRun = {
  started_at: string;
  finished_at: string;
  searches: number;
  failed: number;
  leads: number;
  auto_dismissed?: number;
};

const runOf = (s: Source): KeywordRun | null => {
  const r = s.filters?.run;
  return r && typeof r === "object" ? (r as KeywordRun) : null;
};
const isCollecting = (s: Source) =>
  !!runOf(s) ||
  (typeof s.filters?.pending_snapshot_id === "string" && !!s.filters.pending_snapshot_id);

const minsSince = (iso: string) =>
  Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 60000));

function RunProgress({ source }: { source: Source }) {
  const [open, setOpen] = useState(false);
  const run = runOf(source);
  if (!run) {
    // Single-snapshot run (older LinkedIn / Glassdoor source kinds).
    const since = source.filters?.pending_since;
    return (
      <span className="text-[11px] text-corp-accent inline-flex items-center gap-1.5">
        <Spinner />
        Collecting from Bright Data
        {typeof since === "string" ? ` · ${minsSince(since)} min` : ""}
      </span>
    );
  }
  // Count searches, not snapshots: a batched run is one snapshot
  // covering every search.
  const weight = (x: RunSnapshot) => x.searches?.length || 1;
  const total = run.snapshots.reduce((n, x) => n + weight(x), 0);
  const done = run.snapshots
    .filter((x) => x.status === "imported" || x.status === "failed")
    .reduce((n, x) => n + weight(x), 0);
  const batched = run.snapshots.some((x) => x.searches?.length);
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="basis-full order-last">
      <button
        type="button"
        className="w-full text-left"
        onClick={() => setOpen((o) => !o)}
        title={
          batched
            ? "All saved searches run as one Bright Data job (a job several searches match is billed once); results import when it finishes."
            : "Each saved search runs as its own Bright Data job; results import as each one finishes."
        }
      >
        <div className="flex items-center gap-2 text-[11px] text-corp-accent">
          <Spinner />
          <span>
            Searching LinkedIn via Bright Data — {done} of {total} searches done ·{" "}
            {run.inserted} lead{run.inserted === 1 ? "" : "s"} imported
            {run.auto_dismissed ? ` · ${run.auto_dismissed} auto-dismissed` : ""} ·{" "}
            {minsSince(run.started_at)} min
          </span>
          <span className="ml-auto text-corp-muted">{open ? "hide" : "details"}</span>
        </div>
        <div className="mt-1 h-1.5 rounded bg-corp-surface2 overflow-hidden">
          <div
            className="h-full bg-corp-accent transition-all duration-700"
            style={{ width: `${Math.max(pct, 4)}%` }}
          />
        </div>
      </button>
      {open ? (
        <ul className="mt-2 space-y-0.5 text-[11px]">
          {run.snapshots.map((x, i) => (
            <Fragment key={x.id ?? i}>
            <li className="flex items-center gap-2">
              <span className="w-4 text-center">
                {x.status === "imported" ? (
                  <span className="text-corp-ok">✓</span>
                ) : x.status === "failed" ? (
                  <span className="text-corp-danger">✕</span>
                ) : x.status === "retry" ? (
                  <span className="text-corp-accent2" title={x.error ?? undefined}>↻</span>
                ) : (
                  <Spinner />
                )}
              </span>
              <span className="truncate">{x.label}</span>
              <span
                className={`ml-auto whitespace-nowrap truncate max-w-[60%] ${
                  x.status === "failed"
                    ? "text-corp-danger"
                    : x.status === "retry"
                      ? "text-corp-accent2"
                      : "text-corp-muted"
                }`}
                title={x.error ?? undefined}
              >
                {x.status === "imported"
                  ? `${x.leads} new${x.auto_dismissed ? ` · ${x.auto_dismissed} auto-dismissed` : ""}${
                      x.found != null && x.found !== x.leads ? ` of ${x.found} found` : ""
                    }`
                  : x.status === "failed"
                    ? x.error ?? "failed"
                    : x.status === "retry"
                      ? x.error ?? "retrying shortly…"
                    : x.status === "queued"
                      ? "waiting to send…"
                    : x.status === "ready"
                      ? "downloading…"
                      : x.status === "starting"
                        ? "queued at Bright Data"
                        : "searching…"}
              </span>
            </li>
            {x.searches?.length ? (
              <li className="pl-6 text-corp-muted space-y-0.5">
                {x.searches.map((label, k) => (
                  <div key={k} className="truncate">· {label}</div>
                ))}
              </li>
            ) : null}
            </Fragment>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function LastRunNote({ source }: { source: Source }) {
  const lr = source.filters?.last_run as LastRun | undefined;
  const lastAuto = source.filters?.last_auto_dismissed;
  if ((!lr || typeof lr !== "object") && typeof lastAuto === "number" && lastAuto > 0) {
    // Non–Bright Data sources only record the last poll's tally.
    return (
      <span className="text-[11px] text-corp-muted">last poll: {lastAuto} auto-dismissed</span>
    );
  }
  if (!lr || typeof lr !== "object" || isCollecting(source)) return null;
  const mins = Math.max(
    1,
    Math.round((new Date(lr.finished_at).getTime() - new Date(lr.started_at).getTime()) / 60000),
  );
  return (
    <span className="text-[11px] text-corp-muted" title={`Finished ${new Date(lr.finished_at).toLocaleString()}`}>
      last import: {lr.searches} search{lr.searches === 1 ? "" : "es"} · {lr.leads} new lead
      {lr.leads === 1 ? "" : "s"}
      {lr.auto_dismissed ? ` · ${lr.auto_dismissed} auto-dismissed` : ""} · {mins} min
      {lr.failed ? ` · ${lr.failed} failed` : ""}
    </span>
  );
}

function Spinner() {
  return (
    <svg className="animate-spin h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
const BD_TIME_RANGES = ["Past 24 hours", "Past week", "Past month", "Any time"];
// LinkedIn's own filter labels — Bright Data passes them through.
const BD_COLUMNS: {
  key: keyof BdInputRow;
  label: string;
  hint: string;
  options?: string[];
}[] = [
  { key: "keyword", label: "Keyword *", hint: 'e.g. "python developer" (quotes = exact phrase)' },
  { key: "location", label: "Location", hint: "e.g. New York" },
  { key: "country", label: "Country", hint: "2-letter code, e.g. US / FR" },
  {
    key: "remote",
    label: "Workplace",
    hint: "LinkedIn's workplace filter — Remote returns only remote jobs",
    options: ["Remote", "Hybrid", "On-site"],
  },
  {
    key: "job_type",
    label: "Job type",
    hint: "LinkedIn's job-type filter",
    options: ["Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer", "Other"],
  },
  {
    key: "experience_level",
    label: "Experience",
    hint: "LinkedIn's experience-level filter",
    options: ["Internship", "Entry level", "Associate", "Mid-Senior level", "Director", "Executive"],
  },
  {
    key: "time_range",
    label: "Time range",
    hint: "used only when the run range is 'each row's own'",
    options: BD_TIME_RANGES,
  },
  { key: "company", label: "Company", hint: "optional company filter" },
  { key: "location_radius", label: "Radius", hint: "optional search radius" },
];

function emptyBdRow(): BdInputRow {
  return {
    location: "",
    keyword: "",
    country: "",
    time_range: "",
    job_type: "",
    experience_level: "",
    remote: "",
    company: "",
    location_radius: "",
  };
}

type SourceForm = {
  id?: number;
  kind: string;
  slug_or_url: string;
  label: string;
  enabled: boolean;
  poll_interval_hours: number;
  lead_ttl_hours: number;
  max_leads_per_poll: number;
  title_include: string;
  title_exclude: string;
  location_include: string;
  location_exclude: string;
  remote_only: boolean;
  // brightdata_keyword only: the saved query rows + run-time range.
  bd_inputs: BdInputRow[];
  bd_time_range: string; // "" = use each row's own time_range
};

function emptyForm(kinds: SourceKind[]): SourceForm {
  return {
    kind: kinds[0]?.kind ?? "greenhouse",
    slug_or_url: "",
    label: "",
    enabled: true,
    poll_interval_hours: 24,
    lead_ttl_hours: 168,
    max_leads_per_poll: 100,
    title_include: "",
    title_exclude: "",
    location_include: "",
    location_exclude: "",
    remote_only: false,
    bd_inputs: [emptyBdRow()],
    bd_time_range: "Past week",
  };
}

function formFromSource(s: Source): SourceForm {
  const f = (s.filters ?? {}) as Record<string, unknown>;
  const rawInputs = Array.isArray(f.inputs) ? (f.inputs as Record<string, unknown>[]) : [];
  const bdInputs: BdInputRow[] = rawInputs.map((r) => ({
    location: String(r.location ?? ""),
    keyword: String(r.keyword ?? ""),
    country: String(r.country ?? ""),
    time_range: String(r.time_range ?? ""),
    job_type: String(r.job_type ?? ""),
    experience_level: String(r.experience_level ?? ""),
    remote: String(r.remote ?? ""),
    company: String(r.company ?? ""),
    location_radius: String(r.location_radius ?? ""),
  }));
  return {
    id: s.id,
    kind: s.kind,
    slug_or_url: s.slug_or_url,
    label: s.label ?? "",
    enabled: s.enabled,
    poll_interval_hours: s.poll_interval_hours,
    lead_ttl_hours: s.lead_ttl_hours,
    max_leads_per_poll: s.max_leads_per_poll ?? 100,
    title_include: (f.title_include as string) ?? "",
    title_exclude: (f.title_exclude as string) ?? "",
    location_include: (f.location_include as string) ?? "",
    location_exclude: (f.location_exclude as string) ?? "",
    remote_only: !!f.remote_only,
    bd_inputs: bdInputs.length ? bdInputs : [emptyBdRow()],
    bd_time_range:
      typeof f.time_range_override === "string"
        ? (f.time_range_override as string)
        : "Past week",
  };
}

function formPayload(f: SourceForm) {
  const filters: Record<string, unknown> = {};
  if (f.title_include.trim()) filters.title_include = f.title_include.trim();
  if (f.title_exclude.trim()) filters.title_exclude = f.title_exclude.trim();
  if (f.location_include.trim())
    filters.location_include = f.location_include.trim();
  if (f.location_exclude.trim())
    filters.location_exclude = f.location_exclude.trim();
  if (f.remote_only) filters.remote_only = true;
  const isBdKeyword = f.kind === BD_KEYWORD_KIND;
  let slug = f.slug_or_url.trim();
  if (isBdKeyword) {
    const rows = f.bd_inputs.filter((r) => r.keyword.trim());
    filters.inputs = rows;
    filters.time_range_override = f.bd_time_range;
    // slug_or_url is just a display summary for this kind.
    slug = rows
      .map((r) => r.keyword + (r.location ? ` @ ${r.location}` : ""))
      .join("; ")
      .slice(0, 500) || "keyword query";
  }
  return {
    kind: f.kind,
    slug_or_url: slug,
    label: f.label.trim() || null,
    enabled: f.enabled,
    filters: Object.keys(filters).length ? filters : null,
    poll_interval_hours: f.poll_interval_hours,
    lead_ttl_hours: f.lead_ttl_hours,
    max_leads_per_poll: f.max_leads_per_poll,
  };
}

export default function LeadsPage() {
  const [kinds, setKinds] = useState<SourceKind[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<SourceForm | null>(null);
  const [savingSource, setSavingSource] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [polling, setPolling] = useState<number | null>(null);
  // Inbox filters / state
  const [stateFilter, setStateFilter] = useState<"new" | "promoted" | "dismissed" | "expired" | "all">(
    "new",
  );
  const [sourceFilter, setSourceFilter] = useState<number | "all">("all");
  const [search, setSearch] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Gmail-style "select all N matching" — acts on every lead matching
  // the current filters server-side, not just the loaded page.
  const [allMatching, setAllMatching] = useState(false);
  const [actionRunning, setActionRunning] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);
  const [totalLeads, setTotalLeads] = useState(0);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Saved keyword filters: edited locally, saved ~0.5s after the last
  // change, then the inbox reloads with them applied server-side.
  const [kwFilters, setKwFilters] = useState<KeywordFilter[]>([]);
  const [kwDirty, setKwDirty] = useState(0);
  const [filtersVersion, setFiltersVersion] = useState(0);
  const [filterCounts, setFilterCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    api
      .get<{ filters: KeywordFilter[] }>("/api/v1/job-leads/filters")
      .then((out) => setKwFilters(out.filters))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!kwDirty) return;
    const t = setTimeout(async () => {
      try {
        const out = await api.put<{ filters: KeywordFilter[] }>("/api/v1/job-leads/filters", {
          filters: kwFilters,
        });
        // Adopt server-assigned ids without clobbering edits made since.
        setKwFilters((cur) => cur.map((f, i) => ({ ...f, id: f.id ?? out.filters[i]?.id })));
        setFiltersVersion((v) => v + 1);
      } catch {
        setErr("Couldn't save keyword filters.");
      }
    }, 500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kwDirty]);

  async function loadAll() {
    setLoading(true);
    setErr(null);
    try {
      const [k, s] = await Promise.all([
        api.get<SourceKind[]>("/api/v1/job-sources/kinds"),
        api.get<Source[]>("/api/v1/job-sources"),
      ]);
      setKinds(k);
      setSources(s);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load sources (HTTP ${e.status}).`
          : "Failed to load sources.",
      );
    } finally {
      setLoading(false);
    }
  }

  function leadFilters() {
    return {
      state: stateFilter,
      source_id: sourceFilter === "all" ? null : sourceFilter,
      q: debouncedSearch || null,
      remote_only: remoteOnly,
      use_filters: true,
    };
  }

  async function loadLeads(pageArg: number = page) {
    try {
      const params = new URLSearchParams();
      params.set("state", stateFilter);
      if (sourceFilter !== "all") params.set("source_id", String(sourceFilter));
      if (debouncedSearch) params.set("q", debouncedSearch);
      if (remoteOnly) params.set("remote_only", "true");
      params.set("use_filters", "true");
      params.set("offset", String(pageArg * pageSize));
      params.set("limit", String(pageSize));
      const out = await api.get<{
        total: number;
        items: Lead[];
        filter_counts?: Record<string, number>;
      }>(`/api/v1/job-leads/page?${params.toString()}`);
      setFilterCounts(out.filter_counts ?? {});
      // Page emptied by an action (e.g. dismissed the last page) — step back.
      if (out.items.length === 0 && out.total > 0 && pageArg > 0) {
        const last = Math.max(0, Math.ceil(out.total / pageSize) - 1);
        setPage(last);
        return;
      }
      setLeads(out.items);
      setTotalLeads(out.total);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load leads (HTTP ${e.status}).`
          : "Failed to load leads.",
      );
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  // While a Bright Data run is collecting, re-check every 10s (quietly —
  // no loading flash). Leads import search by search, so the inbox is
  // refreshed whenever the imported count moves.
  const pendingIds = sources.filter(isCollecting).map((s) => s.id).join(",");
  useEffect(() => {
    if (!pendingIds) return;
    let lastTotal = -1;
    const t = setInterval(async () => {
      try {
        const s = await api.get<Source[]>("/api/v1/job-sources");
        setSources(s);
        const total = s.reduce(
          (n, src) => n + (src.total_lead_count ?? 0),
          0,
        );
        if (total !== lastTotal || !s.some(isCollecting)) {
          lastTotal = total;
          void loadLeads();
        }
      } catch {
        /* next tick retries */
      }
    }, 10000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingIds]);

  // Filters changed → back to page 1 with a fresh selection.
  useEffect(() => {
    setSelected(new Set());
    setAllMatching(false);
    if (page !== 0) setPage(0);
    else void loadLeads(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateFilter, sourceFilter, remoteOnly, debouncedSearch, pageSize, filtersVersion]);

  useEffect(() => {
    void loadLeads(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  async function saveSource(form: SourceForm) {
    setSavingSource(true);
    setErr(null);
    try {
      const body = formPayload(form);
      if (form.id) {
        await api.put<Source>(`/api/v1/job-sources/${form.id}`, body);
      } else {
        await api.post<Source>("/api/v1/job-sources", body);
      }
      setEditing(null);
      await loadAll();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Save failed (HTTP ${e.status}).`
          : "Save failed.",
      );
    } finally {
      setSavingSource(false);
    }
  }

  async function deleteSource(id: number) {
    if (!confirm("Delete this source? Existing leads stay; new ones stop arriving.")) return;
    await api.delete(`/api/v1/job-sources/${id}`);
    await loadAll();
  }

  async function seedDefaults() {
    setSeeding(true);
    setErr(null);
    try {
      const out = await api.post<{ created: number; skipped: number }>(
        "/api/v1/job-sources/seed-defaults",
        {},
      );
      await loadAll();
      // Light status — re-use err slot only for failure; success is
      // self-evident from the populated list.
      if (out.created === 0 && out.skipped > 0) {
        setErr(
          `All ${out.skipped} default sources already exist for your account.`,
        );
      }
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Seed failed (HTTP ${e.status}).`
          : "Seed failed.",
      );
    } finally {
      setSeeding(false);
    }
  }

  async function pollNow(id: number) {
    setPolling(id);
    setErr(null);
    try {
      await api.post<Source>(`/api/v1/job-sources/${id}/poll`, {});
      await Promise.all([loadAll(), loadLeads()]);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Poll failed (HTTP ${e.status}).`
          : "Poll failed.",
      );
    } finally {
      setPolling(null);
    }
  }

  function toggleLeadSelection(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllVisibleLeads() {
    setAllMatching(false);
    setSelected((prev) => {
      const visibleIds = leads.map((l) => l.id);
      const allSelected = visibleIds.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allSelected) {
        for (const id of visibleIds) next.delete(id);
      } else {
        for (const id of visibleIds) next.add(id);
      }
      return next;
    });
  }

  const pageAllSelected = leads.length > 0 && leads.every((l) => selected.has(l.id));
  const selectionCount = allMatching ? totalLeads : selected.size;

  async function bulkAction(action: "review" | "dismissed") {
    if (selectionCount === 0) return;
    if (
      allMatching &&
      action === "review" &&
      !window.confirm(
        `Add all ${totalLeads.toLocaleString()} matching leads to the tracker? Each one is ` +
          "imported and scored (one Jev call each). Up to 500 are added per click.",
      )
    )
      return;
    setActionRunning(true);
    setActionMsg(null);
    setErr(null);
    try {
      const out = await api.post<{ promoted: number; dismissed: number; remaining?: number }>(
        "/api/v1/job-leads/action",
        allMatching
          ? { all_matching: leadFilters(), action }
          : { ids: [...selected], action },
      );
      const pieces: string[] = [];
      if (out.promoted > 0)
        pieces.push(
          `${out.promoted} added to tracker as to_review (queued for fetch + scoring)`,
        );
      if (out.dismissed > 0) pieces.push(`${out.dismissed.toLocaleString()} dismissed`);
      if (out.remaining)
        pieces.push("more matching leads remain — click Add to tracker again for the next 500");
      setActionMsg(pieces.join(" · ") || `Action ${action} applied`);
      setSelected(new Set());
      setAllMatching(false);
      await loadLeads();
      // Refresh source counts too — promoted leads change the new_lead_count.
      void loadAll();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Action failed (HTTP ${e.status}).`
          : "Action failed.",
      );
    } finally {
      setActionRunning(false);
    }
  }

  return (
    <PageShell
      title="Job Leads"
      subtitle="ATS feeds polled on your schedule. Triage the inbox, promote interesting rows to the tracker — they auto-queue for scoring."
      actions={
        <div className="flex gap-2">
          <button
            className="jsp-btn-ghost"
            onClick={seedDefaults}
            disabled={seeding}
            title="Insert a small library of known-good Greenhouse / Lever / Ashby / RSS / YC sources, all DISABLED so nothing polls until you toggle them on. Several have regex filter examples baked in to copy from."
          >
            {seeding ? "Seeding…" : "Load examples"}
          </button>
          <button
            className="jsp-btn-primary"
            onClick={() => setEditing(emptyForm(kinds))}
            disabled={!!editing || kinds.length === 0}
          >
            + Add source
          </button>
        </div>
      }
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger mb-3">{err}</div>
      ) : null}

      {editing ? (
        <SourceEditor
          form={editing}
          kinds={kinds}
          saving={savingSource}
          onCancel={() => setEditing(null)}
          onChange={setEditing}
          onSave={() => saveSource(editing)}
        />
      ) : null}

      <section className="jsp-card p-4 mb-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Sources ({sources.length})
          </h3>
        </div>
        {loading ? (
          <p className="text-corp-muted text-sm">Loading…</p>
        ) : sources.length === 0 ? (
          <div className="text-sm text-corp-muted space-y-2">
            <p>
              No sources yet. Click <b>+ Add source</b> to register one — start
              with a Greenhouse / Lever / Ashby / Workable company slug, or
              paste an RSS / Atom feed URL.
            </p>
            <p>
              Or click{" "}
              <button
                type="button"
                className="text-corp-accent hover:underline"
                onClick={seedDefaults}
                disabled={seeding}
              >
                Load examples
              </button>{" "}
              to seed a starter library (all disabled — toggle on whichever
              you actually want polled). Several include regex filter
              examples worth copying.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-corp-border">
            {sources.map((s) => (
              <li
                key={s.id}
                className="py-2 flex flex-wrap items-center gap-2"
              >
                <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border shrink-0">
                  {s.kind}
                </span>
                <span className="font-medium text-sm">
                  {s.label || s.slug_or_url}
                </span>
                <span className="text-[11px] text-corp-muted truncate max-w-xs">
                  {s.label ? s.slug_or_url : ""}
                </span>
                <span className="ml-auto text-[11px] text-corp-muted">
                  every {s.poll_interval_hours}h · TTL {s.lead_ttl_hours}h · top {s.max_leads_per_poll ?? 100}
                </span>
                {s.new_lead_count != null && s.new_lead_count > 0 ? (
                  <span className="text-[11px] text-corp-accent">
                    {s.new_lead_count} new
                  </span>
                ) : null}
                {isCollecting(s) ? (
                  <RunProgress source={s} />
                ) : s.last_error ? (
                  <span
                    className="text-[11px] text-corp-danger truncate max-w-xs"
                    title={s.last_error}
                  >
                    error: {s.last_error}
                  </span>
                ) : null}
                <LastRunNote source={s} />
                <span className="text-[11px] text-corp-muted">
                  {s.last_polled_at
                    ? `polled ${new Date(s.last_polled_at).toLocaleString()}`
                    : "never polled"}
                </span>
                {!s.enabled ? (
                  <span className="text-[11px] text-corp-muted">disabled</span>
                ) : null}
                <button
                  type="button"
                  className="jsp-btn-ghost text-xs"
                  onClick={() => pollNow(s.id)}
                  disabled={polling === s.id || isCollecting(s)}
                  title={
                    isCollecting(s)
                      ? "A run is already being collected — results import automatically when it finishes."
                      : s.kind === BD_KEYWORD_KIND
                      ? `Run the saved keyword query now (${
                          (s.filters?.time_range_override as string) ||
                          "each row's own time range"
                        }). Large runs keep collecting in the background.`
                      : "Poll this source now"
                  }
                >
                  {polling === s.id
                    ? "…"
                    : isCollecting(s)
                      ? "Collecting…"
                      : s.kind === BD_KEYWORD_KIND
                      ? "Import now"
                      : "Poll now"}
                </button>
                <button
                  type="button"
                  className="jsp-btn-ghost text-xs"
                  onClick={() => setEditing(formFromSource(s))}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                  onClick={() => deleteSource(s.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="jsp-card p-4">
        <div className="flex flex-wrap gap-2 items-end mb-3">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted mr-2">
            Inbox
          </h3>
          <div>
            <label className="jsp-label">State</label>
            <select
              className="jsp-input"
              value={stateFilter}
              onChange={(e) =>
                setStateFilter(e.target.value as typeof stateFilter)
              }
            >
              <option value="new">New</option>
              <option value="promoted">Promoted</option>
              <option value="dismissed">Dismissed</option>
              <option value="expired">Expired</option>
              <option value="all">All</option>
            </select>
          </div>
          <div>
            <label className="jsp-label">Source</label>
            <select
              className="jsp-input"
              value={sourceFilter}
              onChange={(e) =>
                setSourceFilter(
                  e.target.value === "all" ? "all" : Number(e.target.value),
                )
              }
            >
              <option value="all">All</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label || s.slug_or_url}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1 min-w-[180px]">
            <label className="jsp-label">Search</label>
            <input
              className="jsp-input"
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="title / org / location"
            />
          </div>
          <label className="text-xs flex items-center gap-1.5 text-corp-muted self-end pb-2">
            <input
              type="checkbox"
              className="accent-corp-accent"
              checked={remoteOnly}
              onChange={(e) => setRemoteOnly(e.target.checked)}
            />
            Remote only
          </label>
          <button
            type="button"
            className="jsp-btn-ghost text-xs self-end"
            onClick={() => loadLeads()}
          >
            Refresh
          </button>
        </div>

        {selectionCount > 0 ? (
          <div className="flex flex-wrap gap-2 items-center mb-3 p-2 bg-corp-accent/10 border border-corp-accent/30 rounded">
            <span className="text-xs text-corp-muted">
              {allMatching
                ? `All ${totalLeads.toLocaleString()} matching leads selected`
                : `${selected.size} selected`}
            </span>
            <button
              type="button"
              className="jsp-btn-primary text-xs"
              onClick={() => bulkAction("review")}
              disabled={actionRunning}
              title="Queue a fetch for each selected lead and add it to the tracker at status=to_review."
            >
              {actionRunning ? "…" : "Add to tracker"}
            </button>
            <button
              type="button"
              className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
              onClick={() => bulkAction("dismissed")}
              disabled={actionRunning}
            >
              Dismiss
            </button>
            <button
              type="button"
              className="jsp-btn-ghost text-xs ml-auto"
              onClick={() => {
                setSelected(new Set());
                setAllMatching(false);
              }}
            >
              Clear
            </button>
            {actionMsg ? (
              <span className="text-[11px] text-corp-muted ml-2">
                {actionMsg}
              </span>
            ) : null}
          </div>
        ) : actionMsg ? (
          <div className="text-[11px] text-corp-muted mb-2">{actionMsg}</div>
        ) : null}

        <KeywordFilters
          filters={kwFilters}
          counts={filterCounts}
          searchText={search}
          onChange={(next) => {
            setKwFilters(next);
            setKwDirty((n) => n + 1);
          }}
        />

        {pageAllSelected && !allMatching && totalLeads > leads.length ? (
          <div className="text-xs mb-3 text-center">
            All {leads.length} leads on this page are selected.{" "}
            <button
              type="button"
              className="text-corp-accent hover:underline"
              onClick={() => setAllMatching(true)}
            >
              Select all {totalLeads.toLocaleString()} matching leads
            </button>
          </div>
        ) : null}

        {leads.length === 0 ? (
          <p className="text-sm text-corp-muted">
            {debouncedSearch
              ? `No leads match "${debouncedSearch}".`
              : stateFilter === "new"
                ? "Inbox zero. Either no sources are polling yet, or you're caught up."
                : "No leads in this filter."}
          </p>
        ) : (
          <>
            <ul className="divide-y divide-corp-border">
              <li className="flex items-center gap-3 py-2 text-[10px] uppercase tracking-wider text-corp-muted">
                <input
                  type="checkbox"
                  className="accent-corp-accent"
                  aria-label="Select all leads on this page"
                  checked={allMatching || pageAllSelected}
                  ref={(el) => {
                    if (el) {
                      const count = leads.filter((l) => selected.has(l.id)).length;
                      el.indeterminate = !allMatching && count > 0 && count < leads.length;
                    }
                  }}
                  onChange={toggleAllVisibleLeads}
                />
                <span className="flex-1">
                  {totalLeads.toLocaleString()} lead{totalLeads === 1 ? "" : "s"}
                </span>
              </li>
              {leads.map((l) => (
                <LeadRow
                  key={l.id}
                  lead={l}
                  selected={allMatching || selected.has(l.id)}
                  onToggle={() => {
                    if (allMatching) {
                      // Leaving "all matching" mode: keep this page, minus this row.
                      setAllMatching(false);
                      setSelected(new Set(leads.map((x) => x.id).filter((id) => id !== l.id)));
                    } else {
                      toggleLeadSelection(l.id);
                    }
                  }}
                />
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2 mt-3 text-xs text-corp-muted">
              <span>
                {(page * pageSize + 1).toLocaleString()}–
                {Math.min((page + 1) * pageSize, totalLeads).toLocaleString()} of{" "}
                {totalLeads.toLocaleString()}
              </span>
              <button
                type="button"
                className="jsp-btn-ghost text-xs"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
              >
                ← Prev
              </button>
              <button
                type="button"
                className="jsp-btn-ghost text-xs"
                onClick={() => setPage((p) => p + 1)}
                disabled={(page + 1) * pageSize >= totalLeads}
              >
                Next →
              </button>
              <label className="ml-auto flex items-center gap-1">
                Per page
                <select
                  className="jsp-input text-xs py-0.5 w-20"
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                >
                  {[50, 100, 250, 500].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </>
        )}
      </section>
    </PageShell>
  );
}

function LeadRow({
  lead,
  selected,
  onToggle,
}: {
  lead: Lead;
  selected: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  // The paged list omits descriptions; fetch on first expand.
  const [body, setBody] = useState<string | null>(lead.description_md ?? null);
  const [bodyLoading, setBodyLoading] = useState(false);
  async function toggle() {
    const next = !expanded;
    setExpanded(next);
    if (next && body === null && lead.has_description !== false) {
      setBodyLoading(true);
      try {
        const out = await api.get<{ description_md: string | null }>(
          `/api/v1/job-leads/${lead.id}/description`,
        );
        setBody(out.description_md ?? "");
      } catch {
        setBody("(couldn't load the description)");
      } finally {
        setBodyLoading(false);
      }
    }
  }
  const subline = [
    lead.organization_name,
    lead.location,
    lead.remote_policy,
    lead.posted_at
      ? `posted ${new Date(lead.posted_at).toLocaleDateString()}`
      : null,
    lead.source_label || lead.source_kind,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li
      className={`py-2 flex flex-col gap-1 ${selected ? "bg-corp-accent/10" : ""}`}
    >
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          className="accent-corp-accent shrink-0"
          checked={selected}
          onChange={onToggle}
          aria-label={`Select ${lead.title}`}
        />
        <div className="flex-1 min-w-0">
          {lead.source_url ? (
            <a
              href={lead.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm hover:text-corp-accent block truncate"
            >
              {lead.title}
            </a>
          ) : (
            <span className="text-sm block truncate">{lead.title}</span>
          )}
          <span className="text-[11px] text-corp-muted truncate block">
            {subline}
          </span>
        </div>
        {lead.tracked_job_id ? (
          <Link
            href={`/jobs/${lead.tracked_job_id}`}
            className="jsp-btn-ghost text-xs shrink-0"
          >
            View tracked →
          </Link>
        ) : null}
        <button
          type="button"
          className="jsp-btn-ghost text-xs shrink-0"
          onClick={() => void toggle()}
          disabled={lead.has_description === false && !body}
          title={lead.has_description === false && !body ? "No description stored" : undefined}
        >
          {expanded ? "Hide" : "Preview"}
        </button>
      </div>
      {expanded ? (
        <pre className="text-[11px] whitespace-pre-wrap text-corp-muted font-sans pl-7 max-h-72 overflow-y-auto">
          {bodyLoading
            ? "Loading…"
            : body
              ? `${body.slice(0, 4000)}${body.length > 4000 ? "…" : ""}`
              : "(no description)"}
        </pre>
      ) : null}
    </li>
  );
}

function SourceEditor({
  form,
  kinds,
  saving,
  onCancel,
  onChange,
  onSave,
}: {
  form: SourceForm;
  kinds: SourceKind[];
  saving: boolean;
  onCancel: () => void;
  onChange: (next: SourceForm) => void;
  onSave: () => void;
}) {
  const activeKind = kinds.find((k) => k.kind === form.kind);
  const hint = activeKind?.hint ?? "";
  const examples = activeKind?.examples ?? [];
  const isBdKeyword = form.kind === BD_KEYWORD_KIND;
  const [csvMsg, setCsvMsg] = useState<string | null>(null);

  async function uploadCsv(file: File | null) {
    if (!file) return;
    setCsvMsg(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(apiUrl("/api/v1/job-sources/parse-keyword-csv"), {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text.slice(0, 300));
      }
      const out = (await res.json()) as {
        inputs: BdInputRow[];
        skipped_rows: number;
      };
      if (!out.inputs.length) {
        setCsvMsg("No usable rows in that CSV (every row needs a keyword).");
        return;
      }
      onChange({ ...form, bd_inputs: out.inputs });
      setCsvMsg(
        `Loaded ${out.inputs.length} row${out.inputs.length === 1 ? "" : "s"}` +
          (out.skipped_rows ? ` (${out.skipped_rows} skipped — no keyword)` : "") +
          ". Save the source to keep them.",
      );
    } catch (e) {
      setCsvMsg(
        `CSV parse failed: ${e instanceof Error ? e.message : "unknown error"}`,
      );
    }
  }

  function setBdRow(i: number, patch: Partial<BdInputRow>) {
    const rows = form.bd_inputs.slice();
    rows[i] = { ...rows[i], ...patch };
    onChange({ ...form, bd_inputs: rows });
  }

  return (
    <div className="jsp-card p-4 mb-3 space-y-3">
      <h3 className="text-sm uppercase tracking-wider text-corp-muted">
        {form.id ? "Edit source" : "Add source"}
      </h3>
      <div className="grid grid-cols-[200px_1fr] gap-3">
        <div>
          <label className="jsp-label">Kind</label>
          <select
            className="jsp-input"
            value={form.kind}
            onChange={(e) => {
              const kind = e.target.value;
              onChange({
                ...form,
                kind,
                // Keyword discovery is a paid weekly import by default.
                ...(kind === BD_KEYWORD_KIND && !form.id
                  ? { poll_interval_hours: 168 }
                  : {}),
              });
            }}
            disabled={saving || !!form.id}
          >
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </div>
        <div className={isBdKeyword ? "hidden" : undefined}>
          <label className="jsp-label">Slug or URL</label>
          <input
            className="jsp-input"
            value={form.slug_or_url}
            onChange={(e) => onChange({ ...form, slug_or_url: e.target.value })}
            placeholder={hint}
            disabled={saving}
          />
          {hint ? (
            <p className="text-[11px] text-corp-muted mt-1">{hint}</p>
          ) : null}
          {examples.length > 0 ? (
            <div className="flex flex-wrap gap-1 mt-1.5">
              <span className="text-[10px] text-corp-muted uppercase tracking-wider mr-1 self-center">
                Try
              </span>
              {examples.map((ex) => (
                <button
                  key={ex.value}
                  type="button"
                  onClick={() => onChange({ ...form, slug_or_url: ex.value })}
                  className="text-[10px] px-1.5 py-0.5 rounded border border-corp-border bg-corp-surface2 text-corp-muted hover:text-corp-accent hover:border-corp-accent uppercase tracking-wider"
                  title={`Use ${ex.value}`}
                  disabled={saving}
                >
                  {ex.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      {isBdKeyword ? (
        <fieldset className="border border-corp-accent/40 rounded p-3 space-y-2">
          <legend className="text-[10px] uppercase tracking-wider text-corp-accent px-2">
            Keyword query (one Bright Data input per row)
          </legend>
          <p className="text-[11px] text-corp-muted">
            {hint} Wrap a keyword in quotes for an exact phrase. Each run
            imports listings from the selected time range below — the
            weekly schedule + &quot;Import now&quot; both use it.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  {BD_COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className="text-left text-[10px] uppercase tracking-wider text-corp-muted font-normal pb-1 pr-2"
                      title={c.hint}
                    >
                      {c.label}
                    </th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {form.bd_inputs.map((row, i) => (
                  <tr key={i}>
                    {BD_COLUMNS.map((c) => (
                      <td key={c.key} className="pr-2 pb-1.5">
                        {c.options ? (
                          <select
                            className="jsp-input text-xs py-1 min-w-[7rem]"
                            value={row[c.key]}
                            onChange={(e) =>
                              setBdRow(i, { [c.key]: e.target.value })
                            }
                            disabled={saving}
                            title={c.hint}
                          >
                            <option value="">Any</option>
                            {/* Keep an unrecognized CSV value selectable rather than dropping it. */}
                            {row[c.key] && !c.options.includes(row[c.key]) ? (
                              <option value={row[c.key]}>{row[c.key]}</option>
                            ) : null}
                            {c.options.map((t) => (
                              <option key={t} value={t}>
                                {t}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input
                            className="jsp-input text-xs py-1"
                            value={row[c.key]}
                            onChange={(e) =>
                              setBdRow(i, { [c.key]: e.target.value })
                            }
                            placeholder={c.hint}
                            disabled={saving}
                          />
                        )}
                      </td>
                    ))}
                    <td className="pb-1.5">
                      <button
                        type="button"
                        className="jsp-btn-ghost text-xs text-corp-danger"
                        onClick={() =>
                          onChange({
                            ...form,
                            bd_inputs:
                              form.bd_inputs.length > 1
                                ? form.bd_inputs.filter((_, j) => j !== i)
                                : [emptyBdRow()],
                          })
                        }
                        disabled={saving}
                        title="Remove this row"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="jsp-btn-ghost text-xs"
              onClick={() =>
                onChange({ ...form, bd_inputs: [...form.bd_inputs, emptyBdRow()] })
              }
              disabled={saving}
            >
              + Add row
            </button>
            <label className="jsp-btn-ghost text-xs cursor-pointer">
              Upload input CSV
              <input
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  uploadCsv(e.target.files?.[0] ?? null);
                  e.target.value = "";
                }}
                disabled={saving}
              />
            </label>
            <span
              className="text-[10px] text-corp-muted"
              title="Header: location,keyword,country,time_range,job_type,experience_level,remote,company,location_radius (job_type / experience_level / remote optional)"
            >
              same CSV format as the Bright Data dashboard export
            </span>
            <div className="ml-auto flex items-center gap-1.5">
              <span className="text-[10px] uppercase tracking-wider text-corp-muted">
                Import time range
              </span>
              <select
                className="jsp-input text-xs py-1 w-44"
                value={form.bd_time_range}
                onChange={(e) =>
                  onChange({ ...form, bd_time_range: e.target.value })
                }
                disabled={saving}
                title="Applied to every row on each run. Pick the empty option to use each row's own time_range instead."
              >
                {BD_TIME_RANGES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
                <option value="">Use each row&apos;s time_range</option>
              </select>
            </div>
          </div>
          {csvMsg ? (
            <p className="text-[11px] text-corp-muted">{csvMsg}</p>
          ) : null}
        </fieldset>
      ) : null}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <label className="jsp-label">Label (optional)</label>
          <input
            className="jsp-input"
            value={form.label}
            onChange={(e) => onChange({ ...form, label: e.target.value })}
            placeholder="Stripe — engineering"
            disabled={saving}
          />
        </div>
        <div>
          <label className="jsp-label">Poll every (hours)</label>
          <input
            className="jsp-input"
            type="number"
            min={1}
            max={720}
            value={form.poll_interval_hours}
            onChange={(e) =>
              onChange({
                ...form,
                poll_interval_hours: Math.max(1, Number(e.target.value) || 24),
              })
            }
            disabled={saving}
          />
        </div>
        <div>
          <label className="jsp-label">Lead expires after (hours)</label>
          <input
            className="jsp-input"
            type="number"
            min={1}
            max={4320}
            value={form.lead_ttl_hours}
            onChange={(e) =>
              onChange({
                ...form,
                lead_ttl_hours: Math.max(1, Number(e.target.value) || 168),
              })
            }
            disabled={saving}
          />
        </div>
        <div>
          <label
            className="jsp-label"
            title="Cap on how many NEW leads any single poll will create. Counts after dedupe and filters. For Bright Data sources this is also passed as the API's limit_per_input to cap spend."
          >
            Top # per poll
          </label>
          <input
            className="jsp-input"
            type="number"
            min={1}
            max={10000}
            value={form.max_leads_per_poll}
            onChange={(e) =>
              onChange({
                ...form,
                max_leads_per_poll: Math.max(
                  1,
                  Number(e.target.value) || 100,
                ),
              })
            }
            disabled={saving}
          />
        </div>
      </div>
      <fieldset className="border border-corp-border rounded p-3">
        <legend className="text-[10px] uppercase tracking-wider text-corp-muted px-2">
          Filters (optional, applied at ingest)
        </legend>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="jsp-label">Title must match (regex)</label>
            <input
              className="jsp-input"
              value={form.title_include}
              onChange={(e) =>
                onChange({ ...form, title_include: e.target.value })
              }
              placeholder="senior|staff|principal"
              disabled={saving}
            />
          </div>
          <div>
            <label className="jsp-label">Title must NOT match (regex)</label>
            <input
              className="jsp-input"
              value={form.title_exclude}
              onChange={(e) =>
                onChange({ ...form, title_exclude: e.target.value })
              }
              placeholder="intern|sales"
              disabled={saving}
            />
          </div>
          <div>
            <label className="jsp-label">Location must match (regex)</label>
            <input
              className="jsp-input"
              value={form.location_include}
              onChange={(e) =>
                onChange({ ...form, location_include: e.target.value })
              }
              placeholder="remote|new york"
              disabled={saving}
            />
          </div>
          <div>
            <label className="jsp-label">Location must NOT match (regex)</label>
            <input
              className="jsp-input"
              value={form.location_exclude}
              onChange={(e) =>
                onChange({ ...form, location_exclude: e.target.value })
              }
              placeholder="germany|netherlands"
              disabled={saving}
            />
          </div>
        </div>
        <label className="text-xs flex items-center gap-1.5 text-corp-muted mt-3">
          <input
            type="checkbox"
            className="accent-corp-accent"
            checked={form.remote_only}
            onChange={(e) =>
              onChange({ ...form, remote_only: e.target.checked })
            }
            disabled={saving}
          />
          Remote only
        </label>
      </fieldset>
      <label className="text-xs flex items-center gap-1.5 text-corp-muted">
        <input
          type="checkbox"
          className="accent-corp-accent"
          checked={form.enabled}
          onChange={(e) => onChange({ ...form, enabled: e.target.checked })}
          disabled={saving}
        />
        Enabled (scheduled polling)
      </label>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          className="jsp-btn-ghost"
          onClick={onCancel}
          disabled={saving}
        >
          Cancel
        </button>
        <button
          type="button"
          className="jsp-btn-primary"
          onClick={onSave}
          disabled={
            saving ||
            (isBdKeyword
              ? !form.bd_inputs.some((r) => r.keyword.trim())
              : !form.slug_or_url.trim())
          }
        >
          {saving ? "Saving…" : form.id ? "Update" : "Create"}
        </button>
      </div>
    </div>
  );
}
