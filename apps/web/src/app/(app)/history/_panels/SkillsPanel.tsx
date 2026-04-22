"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Skill } from "@/lib/types";

export function SkillsPanel() {
  const [items, setItems] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mergeOpen, setMergeOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Skill | null>(null);

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
        <ul className="jsp-card divide-y divide-corp-border overflow-hidden">
          {filtered.map((s) => (
            <SkillRow
              key={s.id}
              skill={s}
              selected={selected.has(s.id)}
              onToggle={() => toggle(s.id)}
              onEdit={() => setEditing(s)}
              onDelete={() => remove(s.id)}
            />
          ))}
        </ul>
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
  onToggle,
  onEdit,
  onDelete,
}: {
  skill: Skill;
  selected: boolean;
  onToggle: () => void;
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
        selected ? "bg-corp-accent/10" : ""
      }`}
    >
      <input
        type="checkbox"
        className="shrink-0 accent-corp-accent"
        checked={selected}
        onChange={onToggle}
        aria-label={`Select ${skill.name}`}
      />
      <div className="min-w-0 flex-1 flex items-baseline gap-2 flex-wrap">
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
      </div>
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
