"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Skill } from "@/lib/types";

type SkillAttachments = {
  work_experiences: {
    id: number;
    title: string;
    organization_id: number | null;
    organization_name: string | null;
    start_date: string | null;
    end_date: string | null;
    usage_notes: string | null;
  }[];
  courses: {
    id: number;
    code: string | null;
    name: string;
    term: string | null;
    start_date: string | null;
    end_date: string | null;
    education_id: number;
    education_degree: string | null;
    organization_id: number | null;
    organization_name: string | null;
    usage_notes: string | null;
  }[];
  other_links: {
    link_id: number;
    other_type: string;
    other_id: number;
    other_label: string;
    relation: string | null;
    note: string | null;
  }[];
};

// Map polymorphic entity_link type → in-app detail page route, when one exists.
// Types not listed here render as plain text (no deep link).
const LINK_ROUTES: Record<string, (id: number) => string> = {
  tracked_job: (id) => `/jobs/${id}`,
  generated_document: (id) => `/studio/${id}`,
};

export function SkillsPanel() {
  const [items, setItems] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mergeOpen, setMergeOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Skill | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const data = await api.get<Skill[]>("/api/v1/history/skills");
      setItems(data);
      setErr(null);
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function remove(id: number) {
    if (!confirm("Delete this skill?")) return;
    await api.delete(`/api/v1/history/skills/${id}`);
    setSelected((s) => {
      const n = new Set(s);
      n.delete(id);
      return n;
    });
    await refresh();
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((s) => {
      if (s.name.toLowerCase().includes(q)) return true;
      for (const a of s.aliases ?? []) {
        if (a.toLowerCase().includes(q)) return true;
      }
      return (s.category ?? "").toLowerCase().includes(q);
    });
  }, [items, query]);

  function toggle(id: number) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  const selectedList = useMemo(
    () => items.filter((s) => selected.has(s.id)),
    [items, selected],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-end justify-between">
        <div>
          <h3 className="text-base text-corp-accent">Skills Catalog</h3>
          <p className="text-[11px] text-corp-muted">
            Skills you add to Work or Courses also appear here. Select two or
            more and merge to collapse duplicates (e.g. "next" + "Next.js"
            into one).
          </p>
        </div>
        <div className="flex gap-2 items-end">
          <div>
            <label className="jsp-label">Search</label>
            <input
              className="jsp-input"
              placeholder="name, alias, category…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => setSelected(new Set())}
            disabled={selected.size === 0}
          >
            Clear selection ({selected.size})
          </button>
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={() => setMergeOpen(true)}
            disabled={selected.size < 2}
            title={
              selected.size < 2
                ? "Select at least two skills to merge"
                : `Merge ${selected.size} selected skills into one`
            }
          >
            Merge selected
          </button>
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={() => setCreating(true)}
          >
            + New
          </button>
        </div>
      </div>

      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}

      {creating ? (
        <SkillForm
          onCancel={() => setCreating(false)}
          onSaved={async () => {
            setCreating(false);
            await refresh();
          }}
        />
      ) : null}

      {editing ? (
        <SkillForm
          initial={editing}
          onCancel={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await refresh();
          }}
        />
      ) : null}

      {loading ? (
        <p className="text-sm text-corp-muted">Loading…</p>
      ) : filtered.length === 0 ? (
        <div className="jsp-card p-5 text-sm text-corp-muted">
          {items.length === 0 ? "No skills yet." : "No skills match that search."}
        </div>
      ) : (
        <div
          className={
            detailId != null
              ? "grid grid-cols-1 lg:grid-cols-[1fr,minmax(320px,420px)] gap-3 items-start"
              : ""
          }
        >
          <ul className="jsp-card divide-y divide-corp-border overflow-hidden">
            {filtered.map((s) => (
              <SkillRow
                key={s.id}
                skill={s}
                selected={selected.has(s.id)}
                active={detailId === s.id}
                onToggle={() => toggle(s.id)}
                onSelect={() =>
                  setDetailId((prev) => (prev === s.id ? null : s.id))
                }
                onEdit={() => setEditing(s)}
                onDelete={() => remove(s.id)}
              />
            ))}
          </ul>
          {detailId != null ? (
            <SkillDetailPanel
              skill={items.find((s) => s.id === detailId) ?? null}
              onClose={() => setDetailId(null)}
            />
          ) : null}
        </div>
      )}

      {mergeOpen ? (
        <MergeModal
          skills={selectedList}
          onCancel={() => setMergeOpen(false)}
          onMerged={async () => {
            setMergeOpen(false);
            setSelected(new Set());
            await refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function SkillRow({
  skill,
  selected,
  active,
  onToggle,
  onSelect,
  onEdit,
  onDelete,
}: {
  skill: Skill;
  selected: boolean;
  active: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const count = skill.attachment_count ?? 0;
  const sub = [
    skill.category,
    skill.proficiency,
    skill.years_experience ? `${skill.years_experience} yrs` : null,
    count === 0 ? "⚠ unattached" : `${count} attachment${count === 1 ? "" : "s"}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <li
      className={`flex items-center gap-3 py-1.5 px-3 hover:bg-corp-surface2 ${
        active
          ? "bg-corp-accent/15 ring-1 ring-inset ring-corp-accent/40"
          : selected
            ? "bg-corp-accent/10"
            : ""
      }`}
    >
      <input
        type="checkbox"
        className="shrink-0 accent-corp-accent"
        checked={selected}
        onChange={onToggle}
        aria-label={`Select ${skill.name}`}
      />
      <button
        type="button"
        onClick={onSelect}
        className="min-w-0 flex-1 flex items-baseline gap-2 flex-wrap text-left hover:text-corp-accent"
        aria-pressed={active}
        title="View attachments"
      >
        <span className="text-sm truncate">{skill.name}</span>
        {skill.aliases && skill.aliases.length > 0 ? (
          <span
            className="text-[10px] text-corp-muted truncate"
            title={`aka ${skill.aliases.join(", ")}`}
          >
            aka {skill.aliases.slice(0, 3).join(", ")}
            {skill.aliases.length > 3 ? ` +${skill.aliases.length - 3}` : ""}
          </span>
        ) : null}
        <span className="text-xs text-corp-muted">· {sub}</span>
      </button>
      <div className="flex gap-1 shrink-0">
        <button className="jsp-btn-ghost text-xs" onClick={onEdit}>
          Edit
        </button>
        <button
          className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
          onClick={onDelete}
        >
          Delete
        </button>
      </div>
    </li>
  );
}

function SkillDetailPanel({
  skill,
  onClose,
}: {
  skill: Skill | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<SkillAttachments | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!skill) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setData(null);
    api
      .get<SkillAttachments>(`/api/v1/history/skills/${skill.id}/attachments`)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) {
          setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [skill?.id]);

  if (!skill) return null;

  const total =
    (data?.work_experiences.length ?? 0) +
    (data?.courses.length ?? 0) +
    (data?.other_links.length ?? 0);

  const evidence = (skill.evidence_notes ?? "").trim();

  return (
    <aside className="jsp-card p-4 space-y-4 sticky top-4 max-h-[calc(100vh-120px)] overflow-auto">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-corp-muted">
            Skill detail
          </div>
          <h4 className="text-base font-semibold truncate">{skill.name}</h4>
          {skill.aliases && skill.aliases.length > 0 ? (
            <div className="text-[11px] text-corp-muted mt-0.5">
              aka {skill.aliases.join(", ")}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          className="jsp-btn-ghost text-xs"
          onClick={onClose}
          title="Close detail panel"
        >
          ×
        </button>
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        {skill.category ? (
          <div>
            <dt className="text-corp-muted">Category</dt>
            <dd>{skill.category}</dd>
          </div>
        ) : null}
        {skill.proficiency ? (
          <div>
            <dt className="text-corp-muted">Proficiency</dt>
            <dd>{skill.proficiency}</dd>
          </div>
        ) : null}
        {skill.years_experience != null ? (
          <div>
            <dt className="text-corp-muted">Years</dt>
            <dd>{skill.years_experience}</dd>
          </div>
        ) : null}
        {skill.last_used_date ? (
          <div>
            <dt className="text-corp-muted">Last used</dt>
            <dd>{skill.last_used_date}</dd>
          </div>
        ) : null}
      </dl>

      {evidence ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Evidence notes
          </div>
          <div className="text-xs whitespace-pre-wrap bg-corp-surface2 border border-corp-border rounded p-2">
            {evidence}
          </div>
        </div>
      ) : null}

      <div>
        <div className="flex items-baseline justify-between mb-1">
          <div className="text-[10px] uppercase tracking-wider text-corp-muted">
            Attachments
          </div>
          <div className="text-[10px] text-corp-muted">
            {loading ? "loading…" : total === 0 ? "none" : `${total} total`}
          </div>
        </div>

        {err ? <div className="text-xs text-corp-danger">{err}</div> : null}

        {!loading && !err && data ? (
          total === 0 ? (
            <div className="text-xs text-corp-muted italic">
              This skill isn't referenced by any work, course, project, job, or
              document yet. Consider attaching it, or delete it if it's stale.
            </div>
          ) : (
            <div className="space-y-3">
              {data.work_experiences.length > 0 ? (
                <section>
                  <h5 className="text-[11px] uppercase tracking-wider text-corp-accent mb-1">
                    Work ({data.work_experiences.length})
                  </h5>
                  <ul className="space-y-1.5">
                    {data.work_experiences.map((w) => (
                      <li
                        key={`w-${w.id}`}
                        className="text-xs bg-corp-surface2 border border-corp-border rounded p-2"
                      >
                        <div className="font-medium truncate">{w.title}</div>
                        <div className="text-corp-muted">
                          {w.organization_name ?? "—"}
                          {w.start_date || w.end_date ? (
                            <>
                              {" · "}
                              {w.start_date ?? "?"} → {w.end_date ?? "current"}
                            </>
                          ) : null}
                        </div>
                        {w.usage_notes ? (
                          <div className="mt-1 text-corp-text/90 italic">
                            “{w.usage_notes}”
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {data.courses.length > 0 ? (
                <section>
                  <h5 className="text-[11px] uppercase tracking-wider text-corp-accent mb-1">
                    Courses ({data.courses.length})
                  </h5>
                  <ul className="space-y-1.5">
                    {data.courses.map((c) => (
                      <li
                        key={`c-${c.id}`}
                        className="text-xs bg-corp-surface2 border border-corp-border rounded p-2"
                      >
                        <div className="font-medium truncate">
                          {c.code ? `${c.code} · ` : ""}
                          {c.name}
                        </div>
                        <div className="text-corp-muted">
                          {c.organization_name ?? "—"}
                          {c.education_degree ? ` · ${c.education_degree}` : ""}
                          {c.term ? ` · ${c.term}` : ""}
                        </div>
                        {c.usage_notes ? (
                          <div className="mt-1 text-corp-text/90 italic">
                            “{c.usage_notes}”
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {data.other_links.length > 0 ? (
                <section>
                  <h5 className="text-[11px] uppercase tracking-wider text-corp-accent mb-1">
                    Other links ({data.other_links.length})
                  </h5>
                  <ul className="space-y-1.5">
                    {data.other_links.map((l) => {
                      const route = LINK_ROUTES[l.other_type]?.(l.other_id);
                      return (
                        <li
                          key={`l-${l.link_id}`}
                          className="text-xs bg-corp-surface2 border border-corp-border rounded p-2"
                        >
                          <div className="flex items-baseline gap-2 flex-wrap">
                            <span className="text-[10px] uppercase text-corp-muted">
                              {l.other_type.replace(/_/g, " ")}
                            </span>
                            {route ? (
                              <Link
                                href={route}
                                className="font-medium text-corp-accent hover:underline truncate"
                              >
                                {l.other_label}
                              </Link>
                            ) : (
                              <span className="font-medium truncate">
                                {l.other_label}
                              </span>
                            )}
                          </div>
                          {l.relation || l.note ? (
                            <div className="text-corp-muted mt-0.5">
                              {l.relation ? `relation: ${l.relation}` : ""}
                              {l.relation && l.note ? " · " : ""}
                              {l.note ?? ""}
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : null}
            </div>
          )
        ) : null}
      </div>
    </aside>
  );
}

function SkillForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial?: Skill;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<Partial<Skill>>(
    initial ?? { name: "", aliases: [] },
  );
  const [aliasText, setAliasText] = useState<string>(
    (initial?.aliases ?? []).join(", "),
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name?.trim()) {
      setErr("Name is required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const aliases = aliasText
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean);
      const payload = {
        name: form.name.trim(),
        category: form.category || null,
        proficiency: form.proficiency || null,
        years_experience: form.years_experience ?? null,
        last_used_date: form.last_used_date || null,
        evidence_notes: form.evidence_notes || null,
        aliases: aliases.length ? aliases : null,
      };
      if (initial?.id) {
        await api.put(`/api/v1/history/skills/${initial.id}`, payload);
      } else {
        await api.post("/api/v1/history/skills", payload);
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="jsp-card p-4 space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Name</label>
          <input
            className="jsp-input"
            value={form.name ?? ""}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div>
          <label className="jsp-label">Category</label>
          <select
            className="jsp-input"
            value={form.category ?? ""}
            onChange={(e) => setForm({ ...form, category: e.target.value || null })}
          >
            <option value="">—</option>
            <option value="technical">technical</option>
            <option value="soft">soft</option>
            <option value="domain">domain</option>
            <option value="tool">tool</option>
            <option value="language">language</option>
          </select>
        </div>
        <div>
          <label className="jsp-label">Proficiency</label>
          <select
            className="jsp-input"
            value={form.proficiency ?? ""}
            onChange={(e) => setForm({ ...form, proficiency: e.target.value || null })}
          >
            <option value="">—</option>
            <option value="novice">novice</option>
            <option value="intermediate">intermediate</option>
            <option value="advanced">advanced</option>
            <option value="expert">expert</option>
          </select>
        </div>
        <div>
          <label className="jsp-label">Years experience</label>
          <input
            type="number"
            step="0.1"
            className="jsp-input"
            value={form.years_experience ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                years_experience: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Last used</label>
          <input
            type="date"
            className="jsp-input"
            value={form.last_used_date ?? ""}
            onChange={(e) => setForm({ ...form, last_used_date: e.target.value || null })}
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Aliases (comma-separated)</label>
          <input
            className="jsp-input"
            value={aliasText}
            onChange={(e) => setAliasText(e.target.value)}
            placeholder="NextJS, next, Next.js"
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Evidence notes</label>
          <textarea
            className="jsp-input min-h-[80px]"
            value={form.evidence_notes ?? ""}
            onChange={(e) =>
              setForm({ ...form, evidence_notes: e.target.value || null })
            }
          />
        </div>
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "Saving…" : initial ? "Save" : "Create"}
        </button>
      </div>
    </form>
  );
}

function MergeModal({
  skills,
  onCancel,
  onMerged,
}: {
  skills: Skill[];
  onCancel: () => void;
  onMerged: () => void;
}) {
  const [keepId, setKeepId] = useState<number>(skills[0]?.id ?? 0);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Preview the resulting alias list.
  const preview = useMemo(() => {
    const keeper = skills.find((s) => s.id === keepId);
    if (!keeper) return null;
    const aliases = new Set<string>();
    const lower = new Set<string>([keeper.name.toLowerCase()]);
    for (const a of keeper.aliases ?? []) {
      aliases.add(a);
      lower.add(a.toLowerCase());
    }
    for (const s of skills) {
      if (s.id === keepId) continue;
      if (!lower.has(s.name.toLowerCase())) {
        aliases.add(s.name);
        lower.add(s.name.toLowerCase());
      }
      for (const a of s.aliases ?? []) {
        if (!lower.has(a.toLowerCase())) {
          aliases.add(a);
          lower.add(a.toLowerCase());
        }
      }
    }
    return {
      keeper_name: keeper.name,
      aliases: Array.from(aliases),
      total_attachments: skills.reduce(
        (sum, s) => sum + (s.attachment_count ?? 0),
        0,
      ),
    };
  }, [skills, keepId]);

  async function merge() {
    setRunning(true);
    setErr(null);
    try {
      await api.post("/api/v1/history/skills/merge", {
        keep_id: keepId,
        merge_ids: skills.filter((s) => s.id !== keepId).map((s) => s.id),
      });
      onMerged();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Merge failed (HTTP ${e.status}).` : "Merge failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <button
        type="button"
        aria-label="close"
        className="fixed inset-0 z-30 bg-black/60"
        onClick={onCancel}
      />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 jsp-card shadow-2xl p-5 w-[min(560px,92vw)] max-h-[85vh] overflow-auto space-y-3">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Merge {skills.length} skills
          </h3>
          <button className="jsp-btn-ghost text-xs" onClick={onCancel} type="button">
            Close
          </button>
        </div>
        <p className="text-[11px] text-corp-muted">
          Pick which name stays as the canonical skill. The others become aliases
          on that row, and every attachment (work / courses / entity links) gets
          re-pointed at the keeper. Merged rows are soft-deleted.
        </p>

        <div className="space-y-1">
          <label className="jsp-label">Keep as canonical</label>
          {skills.map((s) => (
            <label
              key={s.id}
              className="flex items-center gap-2 text-sm py-0.5 cursor-pointer"
            >
              <input
                type="radio"
                name="keep"
                value={s.id}
                checked={keepId === s.id}
                onChange={() => setKeepId(s.id)}
                className="accent-corp-accent"
              />
              <span className="flex-1">
                <strong>{s.name}</strong>
                {s.aliases && s.aliases.length > 0 ? (
                  <span className="text-[11px] text-corp-muted">
                    {" "}· aka {s.aliases.join(", ")}
                  </span>
                ) : null}
                <span className="text-[11px] text-corp-muted">
                  {" "}·{" "}
                  {s.attachment_count ?? 0} attachment
                  {s.attachment_count === 1 ? "" : "s"}
                </span>
              </span>
            </label>
          ))}
        </div>

        {preview ? (
          <div className="jsp-card p-3 bg-corp-surface2 text-sm">
            <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
              Result preview
            </div>
            <div>
              <strong>{preview.keeper_name}</strong>
              {preview.aliases.length > 0 ? (
                <span className="text-[11px] text-corp-muted">
                  {" "}· aliases: {preview.aliases.join(", ")}
                </span>
              ) : null}
            </div>
            <div className="text-[11px] text-corp-muted mt-1">
              {preview.total_attachments} attachment
              {preview.total_attachments === 1 ? "" : "s"} will be consolidated
              onto this row.
            </div>
          </div>
        ) : null}

        {err ? <div className="text-xs text-corp-danger">{err}</div> : null}

        <div className="flex justify-end gap-2">
          <button className="jsp-btn-ghost" onClick={onCancel} type="button">
            Cancel
          </button>
          <button
            className="jsp-btn-primary"
            onClick={merge}
            disabled={running || skills.length < 2}
            type="button"
          >
            {running ? "Merging…" : "Merge"}
          </button>
        </div>
      </div>
    </>
  );
}
