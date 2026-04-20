"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api } from "@/lib/api";
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

  async function refresh() {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (typeFilter) params.set("type", typeFilter);
    params.set("limit", "200");
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
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {items.map((o) => (
            <OrganizationCard key={o.id} summary={o} onEdit={openEdit} onDelete={remove} />
          ))}
        </ul>
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

  useEffect(() => {
    api.get<OrganizationUsage>(`/api/v1/organizations/${summary.id}/usage`).then(setUsage);
  }, [summary.id]);

  const total = usage
    ? usage.work_experiences + usage.educations + usage.tracked_jobs + usage.contacts
    : 0;

  return (
    <li className="jsp-card p-4 flex justify-between gap-3">
      <div>
        <div className="flex items-baseline gap-2">
          <div className="font-medium">{summary.name}</div>
          <span className="text-[10px] uppercase tracking-wider text-corp-muted">
            {summary.type}
          </span>
        </div>
        {usage ? (
          total > 0 ? (
            <div className="text-xs text-corp-muted mt-1">
              {usage.work_experiences > 0 ? `${usage.work_experiences} work · ` : ""}
              {usage.educations > 0 ? `${usage.educations} education · ` : ""}
              {usage.tracked_jobs > 0 ? `${usage.tracked_jobs} jobs · ` : ""}
              {usage.contacts > 0 ? `${usage.contacts} contacts` : ""}
            </div>
          ) : (
            <div className="text-xs text-corp-muted mt-1">Unused</div>
          )
        ) : null}
      </div>
      <div className="flex gap-2 shrink-0">
        <button className="jsp-btn-ghost" onClick={() => onEdit(summary)}>
          Edit
        </button>
        <button
          className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
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
  });

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
      </div>
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
