"use client";

import { useCallback, useEffect, useState } from "react";
import { OrganizationCombobox } from "@/components/OrganizationCombobox";
import { RelatedItemsPanel } from "@/components/RelatedItemsPanel";
import { SkillMultiSelect } from "@/components/SkillMultiSelect";
import { api } from "@/lib/api";
import type { Course, Education } from "@/lib/types";

export function EducationPanel() {
  const [items, setItems] = useState<Education[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Education | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setItems(await api.get<Education[]>("/api/v1/history/education"));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function save(payload: Partial<Education>, id?: number) {
    if (id) await api.put(`/api/v1/history/education/${id}`, payload);
    else await api.post("/api/v1/history/education", payload);
    setCreating(false);
    setEditing(null);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Delete this education entry? Courses under it will be detached.")) return;
    await api.delete(`/api/v1/history/education/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted">
          Education
        </h2>
        {!creating && !editing ? (
          <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
            + Add Education
          </button>
        ) : null}
      </div>

      {creating ? (
        <div className="jsp-card p-4">
          <EducationForm
            onCancel={() => setCreating(false)}
            onSaved={() => {
              setCreating(false);
              refresh();
            }}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted text-sm">Loading...</p>
      ) : items.length === 0 && !creating ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">
          No education recorded.
        </div>
      ) : (
        <ul className="space-y-3">
          {items.map((e) =>
            editing?.id === e.id ? (
              <li key={e.id} className="jsp-card p-4 space-y-4">
                <EducationForm
                  initial={e}
                  onCancel={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    refresh();
                  }}
                />
                <CoursesPanel educationId={e.id} editable />
                <RelatedItemsPanel fromType="education" fromId={e.id} />
              </li>
            ) : (
              <li key={e.id} className="jsp-card p-4">
                <div className="flex justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">
                      {e.degree ? `${e.degree} ` : ""}
                      {e.field_of_study ?? ""}
                    </div>
                    {e.organization_name ? (
                      <div className="text-sm text-corp-muted">
                        {e.organization_name}
                      </div>
                    ) : null}
                    <div className="text-sm text-corp-muted">
                      {e.start_date ?? "?"} → {e.end_date ?? "current"}
                      {e.gpa ? ` · GPA ${e.gpa}` : ""}
                    </div>
                    <CoursesPanel educationId={e.id} editable={false} />
                    <div className="mt-2">
                      <RelatedItemsPanel
                        fromType="education"
                        fromId={e.id}
                        readOnly
                      />
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button className="jsp-btn-ghost" onClick={() => setEditing(e)}>
                      Edit
                    </button>
                    <button
                      className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
                      onClick={() => remove(e.id)}
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

// ----- Nested courses under a single Education ------------------------------

function CoursesPanel({
  educationId,
  editable,
}: {
  educationId: number;
  editable: boolean;
}) {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Course | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setCourses(
        await api.get<Course[]>(
          `/api/v1/history/courses?education_id=${educationId}`,
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [educationId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function save(payload: Partial<Course>, id?: number) {
    const body = { ...payload, education_id: educationId };
    if (id) await api.put(`/api/v1/history/courses/${id}`, body);
    else await api.post("/api/v1/history/courses", body);
    setAdding(false);
    setEditing(null);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Delete this course?")) return;
    await api.delete(`/api/v1/history/courses/${id}`);
    await refresh();
  }

  // Compact read-only rendering — no header controls or row action buttons.
  if (!editable) {
    if (loading) return null;
    if (courses.length === 0) {
      return (
        <div className="mt-3">
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Courses
          </div>
          <div className="text-xs text-corp-muted">—</div>
        </div>
      );
    }
    return (
      <div className="mt-3 space-y-2">
        <div className="text-[10px] uppercase tracking-wider text-corp-muted">
          Courses
        </div>
        <ul className="space-y-1">
          {courses.map((c) => (
            <li
              key={c.id}
              className="border border-corp-border rounded px-2 py-1.5"
            >
              <div className="text-sm">
                {c.code ? `${c.code} · ` : ""}
                {c.name}
                {c.term || c.grade ? (
                  <span className="text-corp-muted text-xs ml-2">
                    {[c.term, c.grade && `Grade: ${c.grade}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
              </div>
              <SkillMultiSelect
                endpoint={`/api/v1/history/courses/${c.id}/skills`}
                readOnly
                emptyLabel=""
              />
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <section className="jsp-card p-4">
      <header className="flex justify-between items-center mb-3">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">Courses</h3>
        {!adding && !editing ? (
          <button className="jsp-btn-ghost text-xs" onClick={() => setAdding(true)}>
            + Course
          </button>
        ) : null}
      </header>

      {adding ? (
        <CourseForm onCancel={() => setAdding(false)} onSubmit={(p) => save(p)} />
      ) : null}

      {loading ? (
        <p className="text-xs text-corp-muted">Loading...</p>
      ) : courses.length === 0 && !adding ? (
        <p className="text-xs text-corp-muted">No courses yet.</p>
      ) : (
        <ul className="space-y-2 mt-2">
          {courses.map((c) => (
            <li key={c.id} className="border border-corp-border rounded p-3">
              {editing?.id === c.id ? (
                <CourseForm
                  initial={c}
                  onCancel={() => setEditing(null)}
                  onSubmit={(p) => save(p, c.id)}
                />
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium text-sm">
                        {c.code ? `${c.code} · ` : ""}
                        {c.name}
                      </div>
                      <div className="text-xs text-corp-muted">
                        {[c.term, c.grade && `Grade: ${c.grade}`, c.instructor]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <button
                        className="jsp-btn-ghost text-xs"
                        onClick={() => setEditing(c)}
                      >
                        Edit
                      </button>
                      <button
                        className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                        onClick={() => remove(c.id)}
                      >
                        ×
                      </button>
                    </div>
                  </div>
                  <div className="mt-2 text-xs text-corp-muted mb-1 uppercase tracking-wider">
                    Skills
                  </div>
                  <SkillMultiSelect
                    endpoint={`/api/v1/history/courses/${c.id}/skills`}
                  />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CourseForm({
  initial,
  onCancel,
  onSubmit,
}: {
  initial?: Course;
  onCancel: () => void;
  onSubmit: (p: Partial<Course>) => Promise<void> | void;
}) {
  const [form, setForm] = useState<Partial<Course>>(initial ?? { name: "" });

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        await onSubmit(form);
      }}
      className="space-y-2 mb-2"
    >
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="jsp-label">Code</label>
          <input
            className="jsp-input"
            value={form.code ?? ""}
            onChange={(e) => setForm({ ...form, code: e.target.value || null })}
            placeholder="e.g. CS 101"
          />
        </div>
        <div>
          <label className="jsp-label">Name *</label>
          <input
            className="jsp-input"
            required
            value={form.name ?? ""}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div>
          <label className="jsp-label">Term</label>
          <input
            className="jsp-input"
            value={form.term ?? ""}
            onChange={(e) => setForm({ ...form, term: e.target.value || null })}
            placeholder="Fall 2022"
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
        <div>
          <label className="jsp-label">Grade</label>
          <input
            className="jsp-input"
            value={form.grade ?? ""}
            onChange={(e) => setForm({ ...form, grade: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">Credits</label>
          <input
            type="number"
            step="0.1"
            className="jsp-input"
            value={form.credits ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                credits: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Instructor</label>
          <input
            className="jsp-input"
            value={form.instructor ?? ""}
            onChange={(e) =>
              setForm({ ...form, instructor: e.target.value || null })
            }
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Notable work</label>
          <textarea
            className="jsp-input min-h-[60px]"
            value={form.notable_work ?? ""}
            onChange={(e) =>
              setForm({ ...form, notable_work: e.target.value || null })
            }
          />
        </div>
      </div>
      <div className="flex justify-end gap-2">
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

function EducationForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial?: Education;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<Partial<Education>>(
    initial ?? { organization_id: null },
  );
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      if (initial?.id) {
        await api.put(`/api/v1/history/education/${initial.id}`, form);
      } else {
        await api.post("/api/v1/history/education", form);
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
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
            onChange={(e) => setForm({ ...form, degree: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">Field of study</label>
          <input
            className="jsp-input"
            value={form.field_of_study ?? ""}
            onChange={(e) =>
              setForm({ ...form, field_of_study: e.target.value || null })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Concentration</label>
          <input
            className="jsp-input"
            value={form.concentration ?? ""}
            onChange={(e) =>
              setForm({ ...form, concentration: e.target.value || null })
            }
            placeholder="Machine learning / Security / …"
          />
        </div>
        <div>
          <label className="jsp-label">GPA</label>
          <input
            type="number"
            step="0.01"
            className="jsp-input"
            value={form.gpa ?? ""}
            onChange={(e) =>
              setForm({ ...form, gpa: e.target.value ? Number(e.target.value) : null })
            }
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
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "..." : "Save"}
        </button>
      </div>
    </form>
  );
}
