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
import { useEffect, useMemo, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

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
};

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
  };
}

function formFromSource(s: Source): SourceForm {
  const f = (s.filters ?? {}) as Record<string, string | boolean | undefined>;
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
  return {
    kind: f.kind,
    slug_or_url: f.slug_or_url.trim(),
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
  const [actionRunning, setActionRunning] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

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

  async function loadLeads() {
    try {
      const params = new URLSearchParams();
      params.set("state", stateFilter);
      if (sourceFilter !== "all") params.set("source_id", String(sourceFilter));
      if (search.trim()) params.set("q", search.trim());
      if (remoteOnly) params.set("remote_only", "true");
      const rows = await api.get<Lead[]>(
        `/api/v1/job-leads?${params.toString()}`,
      );
      setLeads(rows);
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

  useEffect(() => {
    loadLeads();
    setSelected(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateFilter, sourceFilter, remoteOnly]);

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
    setSelected((prev) => {
      const visibleIds = filteredLeads.map((l) => l.id);
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

  const filteredLeads = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter((l) => {
      if (l.title.toLowerCase().includes(q)) return true;
      if ((l.organization_name ?? "").toLowerCase().includes(q)) return true;
      if ((l.location ?? "").toLowerCase().includes(q)) return true;
      return false;
    });
  }, [leads, search]);

  async function bulkAction(action: "review" | "dismissed") {
    if (selected.size === 0) return;
    setActionRunning(true);
    setActionMsg(null);
    setErr(null);
    try {
      const out = await api.post<{ promoted: number; dismissed: number }>(
        "/api/v1/job-leads/action",
        { ids: [...selected], action },
      );
      const pieces: string[] = [];
      if (out.promoted > 0)
        pieces.push(
          `${out.promoted} added to tracker as to_review (queued for fetch + scoring)`,
        );
      if (out.dismissed > 0) pieces.push(`${out.dismissed} dismissed`);
      setActionMsg(pieces.join(" · ") || `Action ${action} applied`);
      setSelected(new Set());
      await loadLeads();
      // Refresh source counts too — promoted leads change the new_lead_count.
      await loadAll();
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
                {s.last_error ? (
                  <span
                    className="text-[11px] text-corp-danger truncate max-w-xs"
                    title={s.last_error}
                  >
                    error: {s.last_error}
                  </span>
                ) : null}
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
                  disabled={polling === s.id}
                >
                  {polling === s.id ? "…" : "Poll now"}
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

        {selected.size > 0 ? (
          <div className="flex flex-wrap gap-2 items-center mb-3 p-2 bg-corp-accent/10 border border-corp-accent/30 rounded">
            <span className="text-xs text-corp-muted">
              {selected.size} selected
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
              onClick={() => setSelected(new Set())}
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

        {filteredLeads.length === 0 ? (
          <p className="text-sm text-corp-muted">
            {stateFilter === "new"
              ? "Inbox zero. Either no sources are polling yet, or you're caught up."
              : "No leads in this filter."}
          </p>
        ) : (
          <ul className="divide-y divide-corp-border">
            <li className="flex items-center gap-3 py-2 text-[10px] uppercase tracking-wider text-corp-muted">
              <input
                type="checkbox"
                className="accent-corp-accent"
                aria-label="Select all visible leads"
                checked={
                  filteredLeads.length > 0 &&
                  filteredLeads.every((l) => selected.has(l.id))
                }
                ref={(el) => {
                  if (el) {
                    const count = filteredLeads.filter((l) =>
                      selected.has(l.id),
                    ).length;
                    el.indeterminate =
                      count > 0 && count < filteredLeads.length;
                  }
                }}
                onChange={toggleAllVisibleLeads}
              />
              <span className="flex-1">{filteredLeads.length} leads</span>
            </li>
            {filteredLeads.map((l) => (
              <LeadRow
                key={l.id}
                lead={l}
                selected={selected.has(l.id)}
                onToggle={() => toggleLeadSelection(l.id)}
              />
            ))}
          </ul>
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
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Hide" : "Preview"}
        </button>
      </div>
      {expanded && lead.description_md ? (
        <pre className="text-[11px] whitespace-pre-wrap text-corp-muted font-sans pl-7 max-h-72 overflow-y-auto">
          {lead.description_md.slice(0, 4000)}
          {lead.description_md.length > 4000 ? "…" : ""}
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
            onChange={(e) => onChange({ ...form, kind: e.target.value })}
            disabled={saving || !!form.id}
          >
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </div>
        <div>
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
          disabled={saving || !form.slug_or_url.trim()}
        >
          {saving ? "Saving…" : form.id ? "Update" : "Create"}
        </button>
      </div>
    </div>
  );
}
