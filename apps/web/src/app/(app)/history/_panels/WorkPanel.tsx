"use client";

import { useEffect, useState } from "react";
import { OrganizationCombobox } from "@/components/OrganizationCombobox";
import { RelatedItemsPanel } from "@/components/RelatedItemsPanel";
import { SkillMultiSelect } from "@/components/SkillMultiSelect";
import { api } from "@/lib/api";
import type { WorkExperience } from "@/lib/types";

export function WorkPanel() {
  const [items, setItems] = useState<WorkExperience[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<WorkExperience | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setItems(await api.get<WorkExperience[]>("/api/v1/history/work"));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function save(payload: Partial<WorkExperience>, id?: number) {
    if (id) await api.put(`/api/v1/history/work/${id}`, payload);
    else await api.post("/api/v1/history/work", payload);
    setCreating(false);
    setEditing(null);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Delete this work entry?")) return;
    await api.delete(`/api/v1/history/work/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted">
          Work Experience
        </h2>
        {!creating && !editing ? (
          <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
            + Add Work
          </button>
        ) : null}
      </div>

      {creating ? (
        <div className="jsp-card p-4">
          <WorkForm
            onCancel={() => setCreating(false)}
            onSaved={async (id) => {
              setCreating(false);
              await refresh();
              // After creating, open edit so user can immediately add skills to it.
              const fresh = await api.get<WorkExperience[]>("/api/v1/history/work");
              const newItem = fresh.find((w) => w.id === id) ?? null;
              setEditing(newItem);
            }}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted text-sm">Loading...</p>
      ) : items.length === 0 && !creating ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">
          No work experience recorded. Add your first entry.
        </div>
      ) : (
        <ul className="space-y-3">
          {items.map((w) =>
            editing?.id === w.id ? (
              <li key={w.id} className="jsp-card p-4 space-y-4">
                <WorkForm
                  initial={w}
                  onCancel={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    refresh();
                  }}
                />
                <section>
                  <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
                    Skills used
                  </h3>
                  <SkillMultiSelect
                    endpoint={`/api/v1/history/work/${w.id}/skills`}
                  />
                </section>
                <RelatedItemsPanel fromType="work" fromId={w.id} />
              </li>
            ) : (
              <li key={w.id} className="jsp-card p-4">
                <div className="flex justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{w.title}</div>
                    <div className="text-sm text-corp-muted">
                      {w.organization_name ? `${w.organization_name} · ` : ""}
                      {w.start_date ?? "?"} → {w.end_date ?? "current"}
                      {w.location ? ` · ${w.location}` : null}
                    </div>
                    {w.summary ? (
                      <p className="text-sm mt-2 text-corp-text whitespace-pre-wrap">
                        {w.summary}
                      </p>
                    ) : null}
                    <div className="mt-3">
                      <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
                        Skills
                      </div>
                      <SkillMultiSelect
                        endpoint={`/api/v1/history/work/${w.id}/skills`}
                        readOnly
                      />
                    </div>
                    <div className="mt-2">
                      <RelatedItemsPanel fromType="work" fromId={w.id} readOnly />
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button className="jsp-btn-ghost" onClick={() => setEditing(w)}>
                      Edit
                    </button>
                    <button
                      className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
                      onClick={() => remove(w.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}

function WorkForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial?: WorkExperience;
  onCancel: () => void;
  onSaved: (id: number) => void;
}) {
  const [organizationId, setOrganizationId] = useState<number | null>(
    initial?.organization_id ?? null,
  );
  const [title, setTitle] = useState(initial?.title ?? "");
  const [startDate, setStartDate] = useState(initial?.start_date ?? "");
  const [endDate, setEndDate] = useState(initial?.end_date ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [employmentType, setEmploymentType] = useState(initial?.employment_type ?? "");
  const [summary, setSummary] = useState(initial?.summary ?? "");
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload: Partial<WorkExperience> = {
        organization_id: organizationId,
        title,
        start_date: startDate || null,
        end_date: endDate || null,
        location: location || null,
        employment_type: employmentType || null,
        summary: summary || null,
      };
      let id = initial?.id;
      if (id) {
        await api.put(`/api/v1/history/work/${id}`, payload);
      } else {
        const created = await api.post<WorkExperience>("/api/v1/history/work", payload);
        id = created.id;
      }
      onSaved(id!);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Organization</label>
          <OrganizationCombobox
            value={organizationId}
            onChange={setOrganizationId}
            defaultTypeOnCreate="company"
          />
        </div>
        <div>
          <label className="jsp-label">Title</label>
          <input
            className="jsp-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="jsp-label">Start date</label>
          <input
            type="date"
            className="jsp-input"
            value={startDate ?? ""}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">End date</label>
          <input
            type="date"
            className="jsp-input"
            value={endDate ?? ""}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Location</label>
          <input
            className="jsp-input"
            value={location ?? ""}
            onChange={(e) => setLocation(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Employment type</label>
          <input
            className="jsp-input"
            placeholder="full_time / contract / ..."
            value={employmentType ?? ""}
            onChange={(e) => setEmploymentType(e.target.value)}
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Summary</label>
          <textarea
            className="jsp-input min-h-[96px]"
            value={summary ?? ""}
            onChange={(e) => setSummary(e.target.value)}
          />
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "..." : "Save"}
        </button>
      </div>
    </form>
  );
}
