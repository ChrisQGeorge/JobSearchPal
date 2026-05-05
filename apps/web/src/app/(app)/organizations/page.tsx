"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { Paginator, usePagination } from "@/components/Paginator";
import { api, ApiError } from "@/lib/api";
import {
  ORG_TYPES,
  type Organization,
  type OrganizationSummary,
  type OrganizationType,
  type OrganizationUsage,
} from "@/lib/types";

export default function OrganizationsPage() {
  const [items, setItems] = useState<OrganizationSummary[]>([]);
  const [q, setQ] = useState("");
  const [typeFilter, setTypeFilter] = useState<OrganizationType | "">("");
  const [editing, setEditing] = useState<Organization | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const pager = usePagination(items, "organizations");

  async function refresh() {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (typeFilter) params.set("type", typeFilter);
    // Larger page so client-side pagination has the whole set; the
    // backend has a hard upper bound it'll honor.
    params.set("limit", "1000");
    setLoading(true);
    try {
      setItems(await api.get<OrganizationSummary[]>(`/api/v1/organizations?${params.toString()}`));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter]);

  useEffect(() => {
    const t = setTimeout(refresh, 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  async function openEdit(summary: OrganizationSummary) {
    const full = await api.get<Organization>(`/api/v1/organizations/${summary.id}`);
    setEditing(full);
  }

  async function saveExisting(updated: Partial<Organization>) {
    if (!editing) return;
    await api.put(`/api/v1/organizations/${editing.id}`, updated);
    setEditing(null);
    await refresh();
  }

  async function createNew(payload: Partial<Organization>) {
    await api.post("/api/v1/organizations", payload);
    setCreating(false);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Delete this organization? It will be detached from any history entries.")) {
      return;
    }
    await api.delete(`/api/v1/organizations/${id}`);
    await refresh();
  }

  return (
    <PageShell
      title="Organizations"
      subtitle="Employers, universities, certifying bodies, conferences — one place for every entity you link your history and applications to."
      actions={
        <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
          + New Organization
        </button>
      }
    >
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div className="flex-1 min-w-[16rem]">
          <label className="jsp-label">Search</label>
          <input
            className="jsp-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter by name"
          />
        </div>
        <div>
          <label className="jsp-label">Type</label>
          <select
            className="jsp-input"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as OrganizationType | "")}
          >
            <option value="">All</option>
            {ORG_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
      </div>

      {creating ? (
        <div className="jsp-card p-4 mb-4">
          <OrganizationForm
            onSubmit={createNew}
            onCancel={() => setCreating(false)}
            submitLabel="Create"
          />
        </div>
      ) : null}

      {editing ? (
        <div className="jsp-card p-4 mb-4">
          <OrganizationForm
            initial={editing}
            onSubmit={saveExisting}
            onCancel={() => setEditing(null)}
            submitLabel="Save"
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted">Loading...</p>
      ) : items.length === 0 ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">
          No organizations yet. Create one above, or let the combobox in the History Editor
          create them for you as you add experiences.
        </div>
      ) : (
        <div className="jsp-card overflow-hidden">
          <ul className="divide-y divide-corp-border">
            {pager.visibleItems.map((o) => (
              <OrganizationCard key={o.id} summary={o} onEdit={openEdit} onDelete={remove} />
            ))}
          </ul>
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

function OrganizationCard({
  summary,
  onEdit,
  onDelete,
}: {
  summary: OrganizationSummary;
  onEdit: (o: OrganizationSummary) => void;
  onDelete: (id: number) => void;
}) {
  const [usage, setUsage] = useState<OrganizationUsage | null>(null);
  const [researching, setResearching] = useState(false);
  const [researchErr, setResearchErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<OrganizationUsage>(`/api/v1/organizations/${summary.id}/usage`).then(setUsage);
  }, [summary.id]);

  async function research() {
    setResearching(true);
    setResearchErr(null);
    try {
      // Fires a Companion activity row; no job listing needed. The endpoint
      // is idempotent — re-running re-populates research_notes / reputation
      // signals / tech_stack_hints for the same org.
      await api.post(`/api/v1/organizations/${summary.id}/research`, {});
    } catch (e) {
      setResearchErr(e instanceof ApiError ? `HTTP ${e.status}` : "failed");
      setTimeout(() => setResearchErr(null), 6000);
    } finally {
      setResearching(false);
    }
  }

  const total = usage
    ? usage.work_experiences + usage.educations + usage.tracked_jobs + usage.contacts
    : 0;

  const usageLabel = usage
    ? total > 0
      ? [
          usage.work_experiences > 0 ? `${usage.work_experiences} work` : null,
          usage.educations > 0 ? `${usage.educations} education` : null,
          usage.tracked_jobs > 0 ? `${usage.tracked_jobs} jobs` : null,
          usage.contacts > 0 ? `${usage.contacts} contacts` : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : "Unused"
    : null;

  return (
    <li className="flex items-center gap-3 py-1.5 px-3 hover:bg-corp-surface2">
      <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border shrink-0">
        {summary.type}
      </span>
      <div className="min-w-0 flex-1 flex items-baseline gap-2">
        <span className="text-sm truncate">{summary.name}</span>
        {usageLabel ? (
          <span className="text-xs text-corp-muted truncate">· {usageLabel}</span>
        ) : null}
      </div>
      <div className="flex gap-1 shrink-0 items-center">
        {researchErr ? (
          <span className="text-[11px] text-corp-danger">{researchErr}</span>
        ) : null}
        <button
          className="jsp-btn-ghost text-xs"
          onClick={research}
          disabled={researching}
          title="Ask the Companion to populate industry, size, description, tech stack hints, and reputation signals. No job listing required."
        >
          {researching ? "Queued…" : "Research"}
        </button>
        <button className="jsp-btn-ghost text-xs" onClick={() => onEdit(summary)}>
          Edit
        </button>
        <button
          className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
          onClick={() => onDelete(summary.id)}
        >
          Delete
        </button>
      </div>
    </li>
  );
}

function OrganizationForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial?: Organization;
  onSubmit: (p: Partial<Organization>) => Promise<void>;
  onCancel: () => void;
  submitLabel: string;
}) {
  const [form, setForm] = useState<Partial<Organization>>({
    name: initial?.name ?? "",
    type: initial?.type ?? "company",
    website: initial?.website ?? null,
    industry: initial?.industry ?? null,
    size: initial?.size ?? null,
    headquarters_location: initial?.headquarters_location ?? null,
    founded_year: initial?.founded_year ?? null,
    description: initial?.description ?? null,
    research_notes: initial?.research_notes ?? null,
  });
  const [snapshot, setSnapshot] = useState<Organization | null>(initial ?? null);
  const [researching, setResearching] = useState(false);
  const [researchHint, setResearchHint] = useState("");
  const [researchErr, setResearchErr] = useState<string | null>(null);

  async function runResearch() {
    if (!initial?.id) return;
    if (!form.name || !form.name.trim()) {
      setResearchErr("Name is required to research this organization.");
      return;
    }
    setResearching(true);
    setResearchErr(null);
    try {
      const updated = await api.post<Organization>(
        `/api/v1/organizations/${initial.id}/research`,
        { hint: researchHint.trim() || null },
      );
      setSnapshot(updated);
      setForm((prev) => ({
        ...prev,
        website: prev.website || updated.website,
        industry: prev.industry || updated.industry,
        size: prev.size || updated.size,
        headquarters_location:
          prev.headquarters_location || updated.headquarters_location,
        founded_year: prev.founded_year || updated.founded_year,
        description: prev.description || updated.description,
        research_notes: updated.research_notes ?? prev.research_notes ?? null,
      }));
      setResearchHint("");
    } catch (e) {
      setResearchErr(
        e instanceof ApiError
          ? `Research failed (HTTP ${e.status}).`
          : "Research failed.",
      );
    } finally {
      setResearching(false);
    }
  }

  const techHints = snapshot?.tech_stack_hints ?? [];
  const sourceLinks = snapshot?.source_links ?? [];
  const reputation = (snapshot?.reputation_signals ?? null) as
    | {
        engineering_culture?: string | null;
        work_life_balance?: string | null;
        layoff_history?: string | null;
        recent_news?: string | null;
        red_flags?: string[] | null;
        green_flags?: string[] | null;
      }
    | null;

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        await onSubmit(form);
      }}
      className="space-y-3"
    >
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="jsp-label">Name</label>
          <input
            className="jsp-input"
            required
            value={form.name ?? ""}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div>
          <label className="jsp-label">Type</label>
          <select
            className="jsp-input"
            value={form.type ?? "company"}
            onChange={(e) =>
              setForm({ ...form, type: e.target.value as OrganizationType })
            }
          >
            {ORG_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Website</label>
          <input
            className="jsp-input"
            value={form.website ?? ""}
            onChange={(e) => setForm({ ...form, website: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">Industry</label>
          <input
            className="jsp-input"
            value={form.industry ?? ""}
            onChange={(e) => setForm({ ...form, industry: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">Size</label>
          <input
            className="jsp-input"
            placeholder="e.g. 11-50"
            value={form.size ?? ""}
            onChange={(e) => setForm({ ...form, size: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">Headquarters</label>
          <input
            className="jsp-input"
            value={form.headquarters_location ?? ""}
            onChange={(e) =>
              setForm({ ...form, headquarters_location: e.target.value || null })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Founded year</label>
          <input
            type="number"
            className="jsp-input"
            value={form.founded_year ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                founded_year: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Description</label>
          <textarea
            className="jsp-input min-h-[80px]"
            value={form.description ?? ""}
            onChange={(e) =>
              setForm({ ...form, description: e.target.value || null })
            }
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Research notes (markdown)</label>
          <textarea
            className="jsp-input min-h-[120px]"
            placeholder="What you've learned that a candidate would actually want before interviewing — history, culture, recent news."
            value={form.research_notes ?? ""}
            onChange={(e) =>
              setForm({ ...form, research_notes: e.target.value || null })
            }
          />
        </div>
      </div>

      {initial?.id ? (
        <div className="jsp-card p-3 bg-corp-surface2 space-y-2">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="text-xs uppercase tracking-wider text-corp-muted">
                Companion research
              </div>
              <p className="text-[11px] text-corp-muted mt-0.5">
                WebSearch + WebFetch. Fills empty fields, refreshes research
                notes and reputation signals, merges tech-stack hints and
                source links.
              </p>
            </div>
            <button
              type="button"
              className="jsp-btn-primary"
              onClick={runResearch}
              disabled={researching}
            >
              {researching ? "Researching..." : "Research company"}
            </button>
          </div>
          <div>
            <input
              className="jsp-input"
              placeholder="Optional focus: 'recent layoffs', 'engineering culture', 'infra stack'..."
              value={researchHint}
              onChange={(e) => setResearchHint(e.target.value)}
              disabled={researching}
            />
          </div>
          {researchErr ? (
            <div className="text-xs text-corp-danger">{researchErr}</div>
          ) : null}

          {techHints.length > 0 ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
                Tech stack hints
              </div>
              <div className="flex flex-wrap gap-1">
                {techHints.map((t) => (
                  <span
                    key={t}
                    className="text-[11px] px-2 py-0.5 rounded bg-corp-surface border border-corp-border text-corp-muted"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {reputation ? (
            <div className="grid grid-cols-2 gap-2 text-xs">
              {reputation.engineering_culture ? (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                    Engineering culture
                  </div>
                  <div>{reputation.engineering_culture}</div>
                </div>
              ) : null}
              {reputation.work_life_balance ? (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                    Work/life balance
                  </div>
                  <div>{reputation.work_life_balance}</div>
                </div>
              ) : null}
              {reputation.layoff_history ? (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                    Layoff history
                  </div>
                  <div>{reputation.layoff_history}</div>
                </div>
              ) : null}
              {reputation.recent_news ? (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                    Recent news
                  </div>
                  <div>{reputation.recent_news}</div>
                </div>
              ) : null}
              {reputation.green_flags && reputation.green_flags.length > 0 ? (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-emerald-300">
                    Green flags
                  </div>
                  <ul className="list-disc list-inside space-y-0.5">
                    {reputation.green_flags.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {reputation.red_flags && reputation.red_flags.length > 0 ? (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-corp-danger">
                    Red flags
                  </div>
                  <ul className="list-disc list-inside space-y-0.5">
                    {reputation.red_flags.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}

          {sourceLinks.length > 0 ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
                Sources consulted
              </div>
              <ul className="text-[11px] space-y-0.5">
                {sourceLinks.map((l, i) => (
                  <li key={i} className="truncate">
                    <a
                      href={l}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-corp-accent hover:underline"
                    >
                      {l}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex gap-2 justify-end">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary">
          {submitLabel}
        </button>
      </div>
    </form>
  );
}
