"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { Skill } from "@/lib/types";

// One entry per JD-mentioned skill name the user doesn't yet have in their
// catalog. Comes from `GET /history/skills/missing-from-jobs`. Names are
// presented in the most-common casing seen across tracked jobs.
type MissingSkill = {
  name: string;
  job_count: number;
  tier_counts: { required?: number; nice_to_have?: number };
  job_ids: number[];
};

// -- Duplicate-detection helpers ---------------------------------------------
// Two catalog skills are "likely duplicates" when their names normalize to
// the same alphanumeric key. Catches case variants ("React"/"react"),
// punctuation variants ("Next.js"/"NextJS"/"next.js"), and whitespace
// variants ("CI/CD"/"cicd"). Doesn't catch abbreviations (K8s/Kubernetes)
// — that'd need a knowledge base.
function _normalizeForDupe(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

// A group is identified by the sorted list of member IDs, joined. The user
// can dismiss a group ("these aren't duplicates"); dismissals live in
// localStorage so the backend stays simple.
const DUPE_DISMISS_KEY = "jsp:skills:dupe_dismissed";

function _loadDupeDismissed(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(DUPE_DISMISS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function _saveDupeDismissed(s: Set<string>) {
  try {
    window.localStorage.setItem(DUPE_DISMISS_KEY, JSON.stringify([...s]));
  } catch {
    /* ignore — storage unavailable */
  }
}

function _groupSignature(ids: number[]): string {
  return [...ids].sort((a, b) => a - b).join(",");
}

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
  const [missing, setMissing] = useState<MissingSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mergeOpen, setMergeOpen] = useState(false);
  const [bulkEditOpen, setBulkEditOpen] = useState(false);
  const [groupMissing, setGroupMissing] = useState<MissingSkill[] | null>(null);
  const [creating, setCreating] = useState(false);
  // editingId replaces the prior `editing` Skill ref so we can render the
  // form INLINE at the editing row's position instead of at the top.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [dupeDismissed, setDupeDismissed] = useState<Set<string>>(() =>
    _loadDupeDismissed(),
  );

  async function refresh() {
    setLoading(true);
    try {
      const [skillData, missingData] = await Promise.all([
        api.get<Skill[]>("/api/v1/history/skills"),
        api
          .get<MissingSkill[]>("/api/v1/history/skills/missing-from-jobs")
          .catch(() => [] as MissingSkill[]),
      ]);
      setItems(skillData);
      setMissing(missingData);
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

  // --- Derived top sections ------------------------------------------------

  const unattached = useMemo(
    () => items.filter((s) => (s.attachment_count ?? 0) === 0),
    [items],
  );

  const dupeGroups = useMemo<Skill[][]>(() => {
    const byKey = new Map<string, Skill[]>();
    for (const s of items) {
      const key = _normalizeForDupe(s.name);
      if (!key) continue;
      const arr = byKey.get(key) ?? [];
      arr.push(s);
      byKey.set(key, arr);
    }
    const out: Skill[][] = [];
    for (const group of byKey.values()) {
      if (group.length < 2) continue;
      const sig = _groupSignature(group.map((s) => s.id));
      if (dupeDismissed.has(sig)) continue;
      out.push(group);
    }
    out.sort((a, b) => b.length - a.length);
    return out;
  }, [items, dupeDismissed]);

  function dismissDupeGroup(ids: number[]) {
    const sig = _groupSignature(ids);
    setDupeDismissed((prev) => {
      const next = new Set(prev);
      next.add(sig);
      _saveDupeDismissed(next);
      return next;
    });
  }

  async function mergeDupeGroup(group: Skill[]) {
    // Pick the skill with the most attachments as the canonical target.
    // Ties break alphabetically to make the choice deterministic.
    const canonical = [...group].sort((a, b) => {
      const ca = a.attachment_count ?? 0;
      const cb = b.attachment_count ?? 0;
      if (ca !== cb) return cb - ca;
      return a.name.localeCompare(b.name);
    })[0];
    const mergeIds = group.filter((s) => s.id !== canonical.id).map((s) => s.id);
    try {
      await api.post("/api/v1/history/skills/merge", {
        keep_id: canonical.id,
        merge_ids: mergeIds,
      });
      await refresh();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Merge failed (HTTP ${e.status}).` : "Merge failed.",
      );
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-end justify-between">
        <div>
          <h3 className="text-base text-corp-accent">Skills Catalog</h3>
          <p className="text-[11px] text-corp-muted">
            Skills you add to Work or Courses also appear here. Select two or
            more and bulk-edit fields, or merge them to collapse duplicates
            (e.g. "next" + "Next.js" into one).
          </p>
        </div>
        <div className="flex gap-2 items-end flex-wrap">
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
            className="jsp-btn-ghost"
            onClick={() => setBulkEditOpen(true)}
            disabled={selected.size < 2}
            title={
              selected.size < 2
                ? "Select at least two skills to bulk-edit"
                : `Apply shared fields to ${selected.size} selected skills`
            }
          >
            Bulk edit
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

      {/* ---- Three hidable top sections ---- */}
      <UnattachedSection
        skills={unattached}
        onEdit={(id) => {
          setEditingId(id);
          setDetailId(null);
        }}
      />
      <DupeSection
        groups={dupeGroups}
        onMerge={mergeDupeGroup}
        onDismiss={dismissDupeGroup}
      />
      <MissingSection
        missing={missing}
        onQuickAdd={async (name) => {
          try {
            await api.post("/api/v1/history/skills", {
              name,
              category: "technical",
            });
            await refresh();
          } catch {
            /* silent — refresh on next fetch or show via main err */
          }
        }}
        onOpenGroup={(picks) => setGroupMissing(picks)}
      />

      {creating ? (
        <SkillForm
          onCancel={() => setCreating(false)}
          onSaved={async () => {
            setCreating(false);
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
            {filtered.map((s) =>
              editingId === s.id ? (
                // Inline form — appears in the list where the row would be.
                // Same SkillForm component as +New but slotted as a <li>.
                <li
                  key={s.id}
                  className="p-3 bg-corp-surface2 border-l-2 border-corp-accent"
                >
                  <SkillForm
                    initial={s}
                    onCancel={() => setEditingId(null)}
                    onSaved={async () => {
                      setEditingId(null);
                      await refresh();
                    }}
                    inline
                  />
                </li>
              ) : (
                <SkillRow
                  key={s.id}
                  skill={s}
                  selected={selected.has(s.id)}
                  active={detailId === s.id}
                  onToggle={() => toggle(s.id)}
                  onSelect={() =>
                    setDetailId((prev) => (prev === s.id ? null : s.id))
                  }
                  onEdit={() => {
                    setEditingId(s.id);
                    setDetailId(null);
                  }}
                  onDelete={() => remove(s.id)}
                />
              ),
            )}
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

      {bulkEditOpen ? (
        <BulkEditModal
          skills={selectedList}
          onCancel={() => setBulkEditOpen(false)}
          onSaved={async () => {
            setBulkEditOpen(false);
            setSelected(new Set());
            await refresh();
          }}
        />
      ) : null}

      {groupMissing ? (
        <GroupMissingModal
          missing={groupMissing}
          onCancel={() => setGroupMissing(null)}
          onSaved={async () => {
            setGroupMissing(null);
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
  const wh = skill.work_history_years ?? null;
  const sub = [
    skill.category,
    skill.proficiency,
    // `work history` is the derived sum across Work rows; keep the
    // self-reported `yrs` alongside so the user can see both.
    wh ? `${wh}y work history` : null,
    skill.years_experience ? `${skill.years_experience}y self-reported` : null,
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
            <dt className="text-corp-muted">Years (self-reported)</dt>
            <dd>{skill.years_experience}</dd>
          </div>
        ) : null}
        {skill.work_history_years != null ? (
          <div>
            <dt className="text-corp-muted" title="Sum of Work durations, rounded up">
              Work history
            </dt>
            <dd>
              {skill.work_history_years} yr
              {skill.work_history_years === 1 ? "" : "s"}
            </dd>
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
  inline,
}: {
  initial?: Skill;
  onCancel: () => void;
  onSaved: () => void;
  // When true, render without the outer jsp-card (caller is already
  // styling the surrounding <li> in the list). Used by the in-list
  // inline-edit mode so the editor appears at the row's position.
  inline?: boolean;
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
    <form
      onSubmit={submit}
      className={inline ? "space-y-3" : "jsp-card p-4 space-y-3"}
    >
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


// ---------------------------------------------------------------------------
// Top-section components
// ---------------------------------------------------------------------------

function CollapseHeader({
  open,
  onToggle,
  title,
  subtitle,
  count,
  tone,
}: {
  open: boolean;
  onToggle: () => void;
  title: string;
  subtitle?: string;
  count: number;
  tone?: "warn" | "danger" | "accent";
}) {
  const countClass =
    tone === "warn"
      ? "text-corp-accent2"
      : tone === "danger"
        ? "text-corp-danger"
        : tone === "accent"
          ? "text-corp-accent"
          : "text-corp-muted";
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-baseline justify-between gap-3 text-left"
    >
      <div className="min-w-0">
        <h4 className="text-sm uppercase tracking-wider text-corp-muted">
          {title}{" "}
          <span className={`normal-case tracking-normal ${countClass}`}>
            ({count})
          </span>
        </h4>
        {subtitle ? (
          <p className="text-[11px] text-corp-muted mt-0.5">{subtitle}</p>
        ) : null}
      </div>
      <span className="text-xs text-corp-muted shrink-0">
        {open ? "hide" : "show"}
      </span>
    </button>
  );
}

// Catalog skills with zero attachments. Renders a compact row per skill
// with an inline "edit" button so the user can quickly attach it to a
// Work/Course or delete it outright.
function UnattachedSection({
  skills,
  onEdit,
}: {
  skills: Skill[];
  onEdit: (id: number) => void;
}) {
  const [open, setOpen] = useState<boolean>(skills.length > 0);
  if (skills.length === 0) return null;
  return (
    <div className="jsp-card p-4">
      <CollapseHeader
        open={open}
        onToggle={() => setOpen((v) => !v)}
        title="Unattached skills"
        subtitle="In your catalog but not linked to any Work, Course, Project, or Job. Attach them or delete the stale ones."
        count={skills.length}
        tone="warn"
      />
      {open ? (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {skills.map((s) => (
            <li
              key={s.id}
              className="inline-flex items-center gap-1 bg-corp-accent2/15 border border-corp-accent2/40 text-corp-accent2 rounded px-2 py-0.5 text-xs"
            >
              {s.name}
              <button
                type="button"
                onClick={() => onEdit(s.id)}
                className="ml-1 bg-corp-accent2/25 hover:bg-corp-accent2/50 rounded px-1 text-[10px] uppercase tracking-wider"
                title="Open this skill's row inline editor"
              >
                edit
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// Groups of catalog skills whose names normalize to the same token.
// Click "Merge" to auto-collapse into the highest-attachment row, or
// "Not duplicates" to dismiss the group (persisted in localStorage).
function DupeSection({
  groups,
  onMerge,
  onDismiss,
}: {
  groups: Skill[][];
  onMerge: (group: Skill[]) => Promise<void>;
  onDismiss: (ids: number[]) => void;
}) {
  const [open, setOpen] = useState<boolean>(groups.length > 0);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  if (groups.length === 0) return null;
  return (
    <div className="jsp-card p-4">
      <CollapseHeader
        open={open}
        onToggle={() => setOpen((v) => !v)}
        title="Likely duplicates"
        subtitle="Catalog entries whose names look like variants of each other (case / punctuation / spacing). Merge to consolidate, or dismiss if they really are distinct."
        count={groups.length}
        tone="warn"
      />
      {open ? (
        <ul className="mt-3 space-y-2">
          {groups.map((group) => {
            const key = group.map((s) => s.id).join(",");
            const busy = busyKey === key;
            return (
              <li
                key={key}
                className="flex items-center gap-2 border border-corp-border rounded p-2 bg-corp-surface2"
              >
                <div className="min-w-0 flex-1 flex flex-wrap gap-1.5">
                  {group.map((s) => (
                    <span
                      key={s.id}
                      className="inline-flex items-baseline gap-1 bg-corp-surface border border-corp-border rounded px-2 py-0.5 text-xs"
                    >
                      <span className="font-medium">{s.name}</span>
                      <span className="text-[10px] text-corp-muted">
                        {s.attachment_count ?? 0}
                      </span>
                    </span>
                  ))}
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    type="button"
                    className="jsp-btn-ghost text-xs"
                    onClick={() => onDismiss(group.map((s) => s.id))}
                    title="These look alike but are actually different skills — hide this suggestion going forward"
                    disabled={busy}
                  >
                    Not duplicates
                  </button>
                  <button
                    type="button"
                    className="jsp-btn-primary text-xs"
                    onClick={async () => {
                      setBusyKey(key);
                      try {
                        await onMerge(group);
                      } finally {
                        setBusyKey(null);
                      }
                    }}
                    disabled={busy}
                    title="Merge into the highest-attachment row, making the others aliases"
                  >
                    {busy ? "Merging…" : "Merge"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

// Skills the user's tracked jobs ask for but aren't in the catalog. Big
// list sorted by job_count desc. Each row shows the name, the count
// (N jobs), and the req/nice breakdown. Two actions: "+ Add" to create
// a single skill, or check the box + click "Group selected" to create
// one canonical skill with the selected names as aliases.
function MissingSection({
  missing,
  onQuickAdd,
  onOpenGroup,
}: {
  missing: MissingSkill[];
  onQuickAdd: (name: string) => Promise<void>;
  onOpenGroup: (picks: MissingSkill[]) => void;
}) {
  const [open, setOpen] = useState<boolean>(missing.length > 0);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return missing;
    return missing.filter((m) => m.name.toLowerCase().includes(q));
  }, [missing, query]);
  const visible = showAll ? filtered : filtered.slice(0, 30);

  function toggle(name: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const pickedList = useMemo(
    () => missing.filter((m) => picked.has(m.name)),
    [missing, picked],
  );

  if (missing.length === 0) return null;
  return (
    <div className="jsp-card p-4">
      <CollapseHeader
        open={open}
        onToggle={() => setOpen((v) => !v)}
        title="Missing from tracked jobs"
        subtitle="Skills your tracked jobs mention that you don't have in your catalog yet. Highest job count first — these are the resume gaps the Companion can't match."
        count={missing.length}
        tone="accent"
      />
      {open ? (
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap gap-2 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="jsp-label">Filter</label>
              <input
                className="jsp-input"
                placeholder="name…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <button
              type="button"
              className="jsp-btn-ghost text-xs"
              onClick={() => setPicked(new Set())}
              disabled={picked.size === 0}
            >
              Clear ({picked.size})
            </button>
            <button
              type="button"
              className="jsp-btn-primary text-xs"
              onClick={() => onOpenGroup(pickedList)}
              disabled={picked.size < 2}
              title={
                picked.size < 2
                  ? "Select at least two missing skills to group"
                  : `Create one canonical skill with ${picked.size} aliases`
              }
            >
              Group selected as one skill
            </button>
          </div>
          <ul className="flex flex-wrap gap-1.5">
            {visible.map((m) => {
              const on = picked.has(m.name);
              const req = m.tier_counts.required ?? 0;
              const nice = m.tier_counts.nice_to_have ?? 0;
              const breakdown =
                req && nice
                  ? `${req} required · ${nice} nice-to-have`
                  : req
                    ? `${req} required`
                    : `${nice} nice-to-have`;
              return (
                <li
                  key={m.name}
                  className={`inline-flex items-center gap-1 border rounded px-2 py-0.5 text-xs transition-colors ${
                    on
                      ? "bg-corp-accent/25 border-corp-accent/60 text-corp-accent"
                      : "bg-corp-accent2/15 border-corp-accent2/40 text-corp-accent2"
                  }`}
                  title={`${m.job_count} job${m.job_count === 1 ? "" : "s"} · ${breakdown}`}
                >
                  <input
                    type="checkbox"
                    className="accent-corp-accent"
                    checked={on}
                    onChange={() => toggle(m.name)}
                    aria-label={`Select ${m.name} for grouping`}
                  />
                  <span className="font-medium">{m.name}</span>
                  <span className="text-[10px] opacity-80">
                    ×{m.job_count}
                  </span>
                  <button
                    type="button"
                    onClick={async () => {
                      setBusy(m.name);
                      try {
                        await onQuickAdd(m.name);
                      } finally {
                        setBusy(null);
                      }
                    }}
                    disabled={busy === m.name}
                    className="ml-1 bg-corp-accent2/25 hover:bg-corp-accent2/50 rounded px-1 text-[10px] uppercase tracking-wider"
                    title="Add this exact name to your catalog"
                  >
                    {busy === m.name ? "…" : "+ Add"}
                  </button>
                </li>
              );
            })}
          </ul>
          {filtered.length > visible.length ? (
            <button
              type="button"
              className="text-[11px] text-corp-accent hover:underline"
              onClick={() => setShowAll(true)}
            >
              Show {filtered.length - visible.length} more…
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Bulk-edit modal — applies shared field values to every selected skill.
// Any field left empty is treated as "leave existing values alone". The
// "Clear field" checkboxes explicitly null a value on every selected row.
// ---------------------------------------------------------------------------

function BulkEditModal({
  skills,
  onCancel,
  onSaved,
}: {
  skills: Skill[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [category, setCategory] = useState<string>("");
  const [proficiency, setProficiency] = useState<string>("");
  const [years, setYears] = useState<string>("");
  const [lastUsed, setLastUsed] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [clearFields, setClearFields] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function toggleClear(field: string) {
    setClearFields((prev) => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  }

  async function run() {
    setRunning(true);
    setErr(null);
    try {
      // Build body — only include fields the user set AND didn't also flag
      // for clearing. The backend treats `clear_fields` as authoritative.
      const body: Record<string, unknown> = {
        ids: skills.map((s) => s.id),
        clear_fields: [...clearFields],
      };
      if (!clearFields.has("category") && category) body.category = category;
      if (!clearFields.has("proficiency") && proficiency)
        body.proficiency = proficiency;
      if (!clearFields.has("years_experience") && years.trim())
        body.years_experience = Number(years);
      if (!clearFields.has("last_used_date") && lastUsed)
        body.last_used_date = lastUsed;
      if (!clearFields.has("evidence_notes") && notes.trim())
        body.evidence_notes = notes.trim();
      await api.post("/api/v1/history/skills/bulk-update", body);
      onSaved();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Update failed (HTTP ${e.status}).` : "Update failed.",
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
            Bulk edit {skills.length} skill{skills.length === 1 ? "" : "s"}
          </h3>
          <button className="jsp-btn-ghost text-xs" onClick={onCancel} type="button">
            Close
          </button>
        </div>
        <p className="text-[11px] text-corp-muted">
          Every field you set below gets written to every selected skill.
          Leave a field blank to leave it alone on each row. Check "clear" to
          null the field on all rows.
        </p>
        <ul className="text-[11px] text-corp-muted max-h-[80px] overflow-auto bg-corp-surface2 border border-corp-border rounded p-2">
          {skills.map((s) => (
            <li key={s.id} className="truncate">
              {s.name}
            </li>
          ))}
        </ul>

        <BulkField label="Category" clearOn={clearFields.has("category")} onClear={() => toggleClear("category")}>
          <select
            className="jsp-input"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            disabled={clearFields.has("category")}
          >
            <option value="">— (unchanged)</option>
            <option value="technical">technical</option>
            <option value="soft">soft</option>
            <option value="domain">domain</option>
            <option value="tool">tool</option>
            <option value="language">language</option>
          </select>
        </BulkField>

        <BulkField
          label="Proficiency"
          clearOn={clearFields.has("proficiency")}
          onClear={() => toggleClear("proficiency")}
        >
          <select
            className="jsp-input"
            value={proficiency}
            onChange={(e) => setProficiency(e.target.value)}
            disabled={clearFields.has("proficiency")}
          >
            <option value="">— (unchanged)</option>
            <option value="novice">novice</option>
            <option value="intermediate">intermediate</option>
            <option value="advanced">advanced</option>
            <option value="expert">expert</option>
          </select>
        </BulkField>

        <BulkField
          label="Years experience"
          clearOn={clearFields.has("years_experience")}
          onClear={() => toggleClear("years_experience")}
        >
          <input
            type="number"
            step="0.1"
            className="jsp-input"
            value={years}
            onChange={(e) => setYears(e.target.value)}
            disabled={clearFields.has("years_experience")}
            placeholder="(unchanged)"
          />
        </BulkField>

        <BulkField
          label="Last used"
          clearOn={clearFields.has("last_used_date")}
          onClear={() => toggleClear("last_used_date")}
        >
          <input
            type="date"
            className="jsp-input"
            value={lastUsed}
            onChange={(e) => setLastUsed(e.target.value)}
            disabled={clearFields.has("last_used_date")}
          />
        </BulkField>

        <BulkField
          label="Evidence notes"
          clearOn={clearFields.has("evidence_notes")}
          onClear={() => toggleClear("evidence_notes")}
        >
          <textarea
            className="jsp-input min-h-[60px]"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={clearFields.has("evidence_notes")}
            placeholder="(unchanged — leave blank to keep each row's current value)"
          />
        </BulkField>

        {err ? <div className="text-xs text-corp-danger">{err}</div> : null}

        <div className="flex justify-end gap-2">
          <button className="jsp-btn-ghost" onClick={onCancel} type="button">
            Cancel
          </button>
          <button
            className="jsp-btn-primary"
            onClick={run}
            disabled={running}
            type="button"
          >
            {running ? "Saving…" : "Apply to all"}
          </button>
        </div>
      </div>
    </>
  );
}

function BulkField({
  label,
  clearOn,
  onClear,
  children,
}: {
  label: string;
  clearOn: boolean;
  onClear: () => void;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="jsp-label mb-0">{label}</label>
        <label className="inline-flex items-center gap-1 text-[10px] text-corp-muted cursor-pointer">
          <input
            type="checkbox"
            className="accent-corp-danger"
            checked={clearOn}
            onChange={onClear}
          />
          clear on all
        </label>
      </div>
      {children}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Group-missing modal — creates ONE canonical skill whose aliases cover
// every selected missing name. The user picks which of the selected names
// becomes the canonical (defaults to the one with the highest job_count).
// ---------------------------------------------------------------------------

function GroupMissingModal({
  missing,
  onCancel,
  onSaved,
}: {
  missing: MissingSkill[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const initialCanonical = useMemo(
    () => [...missing].sort((a, b) => b.job_count - a.job_count)[0]?.name ?? "",
    [missing],
  );
  const [canonical, setCanonical] = useState<string>(initialCanonical);
  const [category, setCategory] = useState<string>("technical");
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const aliases = useMemo(
    () => missing.map((m) => m.name).filter((n) => n !== canonical),
    [missing, canonical],
  );

  async function run() {
    if (!canonical) {
      setErr("Pick a canonical name.");
      return;
    }
    setRunning(true);
    setErr(null);
    try {
      await api.post("/api/v1/history/skills", {
        name: canonical,
        category,
        aliases,
      });
      onSaved();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Create failed (HTTP ${e.status}).` : "Create failed.",
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
            Group {missing.length} missing skills
          </h3>
          <button className="jsp-btn-ghost text-xs" onClick={onCancel} type="button">
            Close
          </button>
        </div>
        <p className="text-[11px] text-corp-muted">
          Pick the canonical name; the others become aliases on the same
          skill. The new row gets this category (default: technical). Future
          JD matches on any of these names will resolve to the same catalog
          entry.
        </p>

        <div>
          <label className="jsp-label">Canonical name</label>
          <div className="space-y-1">
            {missing.map((m) => (
              <label
                key={m.name}
                className="flex items-center gap-2 text-sm py-0.5 cursor-pointer"
              >
                <input
                  type="radio"
                  name="canonical"
                  value={m.name}
                  checked={canonical === m.name}
                  onChange={() => setCanonical(m.name)}
                  className="accent-corp-accent"
                />
                <span className="flex-1">
                  <strong>{m.name}</strong>
                  <span className="text-[11px] text-corp-muted">
                    {" "}· {m.job_count} job{m.job_count === 1 ? "" : "s"}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="jsp-label">Category</label>
          <select
            className="jsp-input"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="technical">technical</option>
            <option value="soft">soft</option>
            <option value="domain">domain</option>
            <option value="tool">tool</option>
            <option value="language">language</option>
          </select>
        </div>

        {aliases.length > 0 ? (
          <div className="jsp-card p-3 bg-corp-surface2 text-sm">
            <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
              Result preview
            </div>
            <div>
              <strong>{canonical}</strong>
              <span className="text-[11px] text-corp-muted">
                {" "}· aliases: {aliases.join(", ")}
              </span>
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
            onClick={run}
            disabled={running || !canonical}
            type="button"
          >
            {running ? "Creating…" : "Create canonical skill"}
          </button>
        </div>
      </div>
    </>
  );
}
