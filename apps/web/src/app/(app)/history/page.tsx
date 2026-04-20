"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { OrganizationCombobox } from "@/components/OrganizationCombobox";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";
import type {
  Achievement,
  Education,
  Skill,
  WorkExperience,
} from "@/lib/types";

type Tab = "work" | "education" | "skills" | "achievements";

const TABS: { key: Tab; label: string }[] = [
  { key: "work", label: "Work" },
  { key: "education", label: "Education" },
  { key: "skills", label: "Skills" },
  { key: "achievements", label: "Achievements" },
];

export default function HistoryEditorPage() {
  const [tab, setTab] = useState<Tab>("work");
  return (
    <PageShell
      title="History Editor"
      subtitle="Your canonical career record. Every AI skill draws from what is recorded here — and nothing else."
    >
      <div className="flex gap-2 mb-4 border-b border-corp-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-2 text-sm transition-colors ${
              tab === t.key
                ? "text-corp-accent border-b-2 border-corp-accent"
                : "text-corp-muted hover:text-corp-text"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "work" && <WorkPanel />}
      {tab === "education" && <EducationPanel />}
      {tab === "skills" && <SkillsPanel />}
      {tab === "achievements" && <AchievementsPanel />}
    </PageShell>
  );
}

// ---------- Work ----------

function WorkPanel() {
  const router = useRouter();
  const [items, setItems] = useState<WorkExperience[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<WorkExperience | null>(null);
  const [creating, setCreating] = useState(false);

  async function refresh() {
    try {
      const r = await api.get<WorkExperience[]>("/api/v1/history/work");
      setItems(r);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(payload: Partial<WorkExperience>, id?: number) {
    if (id) await api.put(`/api/v1/history/work/${id}`, payload);
    else await api.post("/api/v1/history/work", payload);
    setEditing(null);
    setCreating(false);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Delete this entry?")) return;
    await api.delete(`/api/v1/history/work/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
          + Add Work
        </button>
      </div>
      {loading ? (
        <p className="text-corp-muted">Loading...</p>
      ) : items.length === 0 && !creating ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">
          No work experience recorded. Add your first entry above.
        </div>
      ) : (
        <ul className="space-y-3">
          {items.map((w) => (
            <li key={w.id} className="jsp-card p-4">
              {editing?.id === w.id ? (
                <WorkForm
                  initial={w}
                  onCancel={() => setEditing(null)}
                  onSubmit={(p) => save(p, w.id)}
                />
              ) : (
                <div className="flex justify-between gap-4">
                  <div>
                    <div className="font-medium">{w.title}</div>
                    <div className="text-sm text-corp-muted">
                      {w.organization_name ? `${w.organization_name} · ` : ""}
                      {w.start_date ?? "?"} → {w.end_date ?? "current"}
                      {w.location ? ` · ${w.location}` : null}
                    </div>
                    {w.summary ? (
                      <p className="text-sm mt-2 text-corp-text">{w.summary}</p>
                    ) : null}
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
              )}
            </li>
          ))}
        </ul>
      )}
      {creating ? (
        <div className="jsp-card p-4">
          <WorkForm onCancel={() => setCreating(false)} onSubmit={(p) => save(p)} />
        </div>
      ) : null}
    </div>
  );
}

function WorkForm({
  initial,
  onSubmit,
  onCancel,
}: {
  initial?: WorkExperience;
  onSubmit: (p: Partial<WorkExperience>) => Promise<void> | void;
  onCancel: () => void;
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await onSubmit({
      organization_id: organizationId,
      title,
      start_date: startDate || null,
      end_date: endDate || null,
      location: location || null,
      employment_type: employmentType || null,
      summary: summary || null,
    });
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
          <input className="jsp-input" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
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
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Location</label>
          <input className="jsp-input" value={location ?? ""} onChange={(e) => setLocation(e.target.value)} />
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
      </div>
      <div>
        <label className="jsp-label">Summary</label>
        <textarea
          className="jsp-input min-h-[96px]"
          value={summary ?? ""}
          onChange={(e) => setSummary(e.target.value)}
        />
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary">
          Save
        </button>
      </div>
    </form>
  );
}

// ---------- Education ----------

function EducationPanel() {
  const [items, setItems] = useState<Education[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  async function refresh() {
    try {
      setItems(await api.get<Education[]>("/api/v1/history/education"));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function save(p: Partial<Education>) {
    await api.post("/api/v1/history/education", p);
    setCreating(false);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Delete this education entry?")) return;
    await api.delete(`/api/v1/history/education/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
          + Add Education
        </button>
      </div>
      {loading ? (
        <p className="text-corp-muted">Loading...</p>
      ) : items.length === 0 && !creating ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">No education recorded.</div>
      ) : (
        <ul className="space-y-3">
          {items.map((e) => (
            <li key={e.id} className="jsp-card p-4 flex justify-between gap-4">
              <div>
                <div className="font-medium">
                  {e.degree ? `${e.degree} ` : ""}
                  {e.field_of_study ?? ""}
                </div>
                {e.organization_name ? (
                  <div className="text-sm text-corp-muted">{e.organization_name}</div>
                ) : null}
                <div className="text-sm text-corp-muted">
                  {e.start_date ?? "?"} → {e.end_date ?? "current"}
                </div>
              </div>
              <button
                className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
                onClick={() => remove(e.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
      {creating ? (
        <EducationForm onCancel={() => setCreating(false)} onSubmit={save} />
      ) : null}
    </div>
  );
}

function EducationForm({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (p: Partial<Education>) => Promise<void>;
}) {
  const [form, setForm] = useState<Partial<Education>>({ organization_id: null });
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        await onSubmit(form);
      }}
      className="jsp-card p-4 space-y-3"
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Institution</label>
          <OrganizationCombobox
            value={form.organization_id ?? null}
            onChange={(id) => setForm({ ...form, organization_id: id })}
            defaultTypeOnCreate="university"
            required
          />
        </div>
        <div>
          <label className="jsp-label">Degree</label>
          <input
            className="jsp-input"
            value={form.degree ?? ""}
            onChange={(e) => setForm({ ...form, degree: e.target.value })}
          />
        </div>
        <div>
          <label className="jsp-label">Field of study</label>
          <input
            className="jsp-input"
            value={form.field_of_study ?? ""}
            onChange={(e) => setForm({ ...form, field_of_study: e.target.value })}
          />
        </div>
        <div>
          <label className="jsp-label">GPA</label>
          <input
            type="number"
            step="0.01"
            className="jsp-input"
            value={form.gpa ?? ""}
            onChange={(e) => setForm({ ...form, gpa: e.target.value ? Number(e.target.value) : null })}
          />
        </div>
        <div>
          <label className="jsp-label">Start date</label>
          <input
            type="date"
            className="jsp-input"
            value={form.start_date ?? ""}
            onChange={(e) => setForm({ ...form, start_date: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">End date</label>
          <input
            type="date"
            className="jsp-input"
            value={form.end_date ?? ""}
            onChange={(e) => setForm({ ...form, end_date: e.target.value || null })}
          />
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary">
          Save
        </button>
      </div>
    </form>
  );
}

// ---------- Skills ----------

function SkillsPanel() {
  const [items, setItems] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("technical");
  const [proficiency, setProficiency] = useState("intermediate");

  async function refresh() {
    try {
      setItems(await api.get<Skill[]>("/api/v1/history/skills"));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await api.post("/api/v1/history/skills", { name, category, proficiency });
    setName("");
    await refresh();
  }

  async function remove(id: number) {
    await api.delete(`/api/v1/history/skills/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-4">
      <form onSubmit={add} className="jsp-card p-4 flex flex-wrap gap-2 items-end">
        <div className="flex-1 min-w-[12rem]">
          <label className="jsp-label">Skill name</label>
          <input className="jsp-input" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div>
          <label className="jsp-label">Category</label>
          <select
            className="jsp-input"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {["technical", "soft", "domain", "tool", "language"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Proficiency</label>
          <select
            className="jsp-input"
            value={proficiency}
            onChange={(e) => setProficiency(e.target.value)}
          >
            {["novice", "intermediate", "advanced", "expert"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </div>
        <button type="submit" className="jsp-btn-primary">Add</button>
      </form>

      {loading ? (
        <p className="text-corp-muted">Loading...</p>
      ) : items.length === 0 ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">No skills recorded.</div>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {items.map((s) => (
            <li key={s.id} className="jsp-card px-3 py-2 text-sm flex gap-3 items-center">
              <div>
                <span className="font-medium">{s.name}</span>
                <span className="text-corp-muted ml-2">
                  {s.category}
                  {s.proficiency ? ` · ${s.proficiency}` : null}
                </span>
              </div>
              <button
                className="text-corp-muted hover:text-corp-danger text-xs"
                onClick={() => remove(s.id)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------- Achievements ----------

function AchievementsPanel() {
  const [items, setItems] = useState<Achievement[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<Partial<Achievement>>({ title: "" });
  const [creating, setCreating] = useState(false);

  async function refresh() {
    try {
      setItems(await api.get<Achievement[]>("/api/v1/history/achievements"));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title?.trim()) return;
    await api.post("/api/v1/history/achievements", form);
    setForm({ title: "" });
    setCreating(false);
    await refresh();
  }

  async function remove(id: number) {
    await api.delete(`/api/v1/history/achievements/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
          + Add Achievement
        </button>
      </div>
      {creating ? (
        <form onSubmit={save} className="jsp-card p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="jsp-label">Title</label>
              <input
                className="jsp-input"
                required
                value={form.title ?? ""}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </div>
            <div>
              <label className="jsp-label">Issuer</label>
              <input
                className="jsp-input"
                value={form.issuer ?? ""}
                onChange={(e) => setForm({ ...form, issuer: e.target.value })}
              />
            </div>
            <div>
              <label className="jsp-label">Date</label>
              <input
                type="date"
                className="jsp-input"
                value={form.date_awarded ?? ""}
                onChange={(e) => setForm({ ...form, date_awarded: e.target.value || null })}
              />
            </div>
            <div className="col-span-2">
              <label className="jsp-label">Description</label>
              <textarea
                className="jsp-input min-h-[80px]"
                value={form.description ?? ""}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button type="button" className="jsp-btn-ghost" onClick={() => setCreating(false)}>
              Cancel
            </button>
            <button type="submit" className="jsp-btn-primary">
              Save
            </button>
          </div>
        </form>
      ) : null}
      {loading ? (
        <p className="text-corp-muted">Loading...</p>
      ) : items.length === 0 && !creating ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">
          No achievements recorded. Modesty is, regrettably, not a competitive advantage.
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((a) => (
            <li key={a.id} className="jsp-card p-4 flex justify-between gap-4">
              <div>
                <div className="font-medium">{a.title}</div>
                <div className="text-sm text-corp-muted">
                  {a.issuer ?? "—"}
                  {a.date_awarded ? ` · ${a.date_awarded}` : null}
                </div>
                {a.description ? (
                  <p className="text-sm mt-1">{a.description}</p>
                ) : null}
              </div>
              <button
                className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
                onClick={() => remove(a.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
