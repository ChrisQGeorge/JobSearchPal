"use client";

import { useEffect, useMemo, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

type Snippet = {
  id: number;
  kind: string;
  title: string;
  content_md: string;
  tags?: string[] | null;
  created_at: string;
  updated_at: string;
};

type SnippetForm = {
  id?: number;
  kind: string;
  title: string;
  content_md: string;
  tags: string;
};

const KIND_LABELS: Record<string, string> = {
  hook: "Hook (opener)",
  bridge: "Bridge (transition)",
  close: "Close",
  anecdote: "Anecdote",
  value_prop: "Value prop",
  other: "Other",
};

const KIND_ORDER = ["hook", "bridge", "anecdote", "value_prop", "close", "other"];

function emptyForm(kind = "hook"): SnippetForm {
  return { kind, title: "", content_md: "", tags: "" };
}

export default function CoverLetterLibraryPage() {
  const [items, setItems] = useState<Snippet[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<SnippetForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [knownKinds, setKnownKinds] = useState<string[]>([
    "hook",
    "bridge",
    "close",
    "anecdote",
    "value_prop",
    "other",
  ]);
  const [filterKind, setFilterKind] = useState<string | "all">("all");

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const rows = await api.get<Snippet[]>("/api/v1/cover-letter-library");
      setItems(rows);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load (HTTP ${e.status}).`
          : "Failed to load.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    api
      .get<string[]>("/api/v1/cover-letter-library/kinds")
      .then((k) => setKnownKinds(k))
      .catch(() => {});
  }, []);

  async function save(form: SnippetForm) {
    setSaving(true);
    setErr(null);
    try {
      const payload = {
        kind: form.kind.trim().toLowerCase(),
        title: form.title.trim(),
        content_md: form.content_md,
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
      if (form.id) {
        await api.put<Snippet>(
          `/api/v1/cover-letter-library/${form.id}`,
          payload,
        );
      } else {
        await api.post<Snippet>("/api/v1/cover-letter-library", payload);
      }
      setEditing(null);
      await refresh();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this snippet?")) return;
    await api.delete(`/api/v1/cover-letter-library/${id}`);
    await refresh();
  }

  const grouped = useMemo(() => {
    const map = new Map<string, Snippet[]>();
    for (const s of items) {
      if (filterKind !== "all" && s.kind !== filterKind) continue;
      const arr = map.get(s.kind) ?? [];
      arr.push(s);
      map.set(s.kind, arr);
    }
    const order = [
      ...KIND_ORDER.filter((k) => map.has(k)),
      ...[...map.keys()].filter((k) => !KIND_ORDER.includes(k)),
    ];
    return order.map((k) => [k, map.get(k) ?? []] as const);
  }, [items, filterKind]);

  return (
    <PageShell
      title="Cover Letter Library"
      subtitle="Reusable hooks, bridges, and closers in your voice. The Companion can pull from this when drafting cover letters so it isn't reinventing every opener."
      actions={
        <button
          className="jsp-btn-primary"
          onClick={() => setEditing(emptyForm())}
          disabled={!!editing}
        >
          + New snippet
        </button>
      }
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger">{err}</div>
      ) : null}

      {editing ? (
        <div className="jsp-card p-4 mb-3 space-y-3">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            {editing.id ? "Edit snippet" : "New snippet"}
          </h3>
          <div className="grid grid-cols-[160px_1fr] gap-3">
            <div>
              <label className="jsp-label">Kind</label>
              <select
                className="jsp-input"
                value={editing.kind}
                onChange={(e) =>
                  setEditing({ ...editing, kind: e.target.value })
                }
                disabled={saving}
              >
                {knownKinds.map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABELS[k] ?? k}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="jsp-label">Title</label>
              <input
                className="jsp-input"
                value={editing.title}
                onChange={(e) =>
                  setEditing({ ...editing, title: e.target.value })
                }
                placeholder='e.g. "Open with rare-skill curiosity"'
                disabled={saving}
              />
            </div>
          </div>
          <div>
            <label className="jsp-label">Content (markdown)</label>
            <textarea
              className="jsp-input font-mono text-sm min-h-[140px]"
              value={editing.content_md}
              onChange={(e) =>
                setEditing({ ...editing, content_md: e.target.value })
              }
              placeholder="Paste the actual snippet — a paragraph or two, not a whole letter."
              disabled={saving}
            />
            <p className="text-[11px] text-corp-muted mt-1">
              Use placeholders like <code>{"{{role}}"}</code> /{" "}
              <code>{"{{company}}"}</code> if you want — the tailor knows to
              fill them in. Otherwise just write straightforward prose.
            </p>
          </div>
          <div>
            <label className="jsp-label">Tags (comma-separated)</label>
            <input
              className="jsp-input"
              value={editing.tags}
              onChange={(e) =>
                setEditing({ ...editing, tags: e.target.value })
              }
              placeholder="senior, tech, bay-area"
              disabled={saving}
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="jsp-btn-ghost"
              onClick={() => setEditing(null)}
              disabled={saving}
            >
              Cancel
            </button>
            <button
              type="button"
              className="jsp-btn-primary"
              onClick={() => save(editing)}
              disabled={
                saving || !editing.title.trim() || !editing.content_md.trim()
              }
            >
              {saving ? "Saving…" : editing.id ? "Update" : "Create"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="jsp-card p-3 mb-3 flex flex-wrap gap-1.5 items-center">
        <span className="text-[11px] text-corp-muted uppercase tracking-wider mr-2">
          Filter
        </span>
        <button
          type="button"
          className={`px-2 py-0.5 rounded-md text-xs uppercase tracking-wider border ${
            filterKind === "all"
              ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
              : "bg-corp-surface2 text-corp-muted border-corp-border"
          }`}
          onClick={() => setFilterKind("all")}
        >
          All ({items.length})
        </button>
        {KIND_ORDER.filter((k) =>
          items.some((i) => i.kind === k),
        ).map((k) => {
          const n = items.filter((i) => i.kind === k).length;
          return (
            <button
              key={k}
              type="button"
              className={`px-2 py-0.5 rounded-md text-xs uppercase tracking-wider border ${
                filterKind === k
                  ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
                  : "bg-corp-surface2 text-corp-muted border-corp-border"
              }`}
              onClick={() => setFilterKind(filterKind === k ? "all" : k)}
            >
              {KIND_LABELS[k] ?? k} ({n})
            </button>
          );
        })}
      </div>

      {loading ? (
        <p className="text-corp-muted">Loading…</p>
      ) : items.length === 0 ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          Empty library. Click <b>+ New snippet</b> to seed it with a few
          hooks and closers you actually like — anything you would otherwise
          re-type from a previous cover letter.
        </div>
      ) : grouped.length === 0 ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          No snippets in that bucket yet.
        </div>
      ) : (
        grouped.map(([kind, rows]) => (
          <div key={kind} className="mb-4">
            <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
              {KIND_LABELS[kind] ?? kind} · {rows.length}
            </h3>
            <ul className="jsp-card divide-y divide-corp-border">
              {rows.map((s) => (
                <li
                  key={s.id}
                  className="px-4 py-3 hover:bg-corp-surface2 flex flex-col gap-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm">{s.title}</span>
                    <div className="flex gap-1.5 shrink-0">
                      <button
                        className="jsp-btn-ghost text-xs"
                        onClick={() =>
                          setEditing({
                            id: s.id,
                            kind: s.kind,
                            title: s.title,
                            content_md: s.content_md,
                            tags: (s.tags ?? []).join(", "),
                          })
                        }
                      >
                        Edit
                      </button>
                      <button
                        className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                        onClick={() => remove(s.id)}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                  <pre className="text-[11px] whitespace-pre-wrap text-corp-muted font-sans line-clamp-4">
                    {s.content_md}
                  </pre>
                  {(s.tags ?? []).length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {(s.tags ?? []).map((t) => (
                        <span
                          key={t}
                          className="inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border"
                        >
                          #{t}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </PageShell>
  );
}
