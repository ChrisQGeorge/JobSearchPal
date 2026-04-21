"use client";

import { useEffect, useRef, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, apiUrl, ApiError } from "@/lib/api";
import type { WritingSample } from "@/lib/types";

export default function SamplesPage() {
  const [samples, setSamples] = useState<WritingSample[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<WritingSample | "new" | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadTags, setUploadTags] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const data = await api.get<WritingSample[]>("/api/v1/documents/samples");
      setSamples(data);
      if (data.length && selectedId === null) setSelectedId(data[0].id);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Failed to load (HTTP ${e.status}).` : "Failed to load.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function remove(id: number) {
    if (!confirm("Delete this sample?")) return;
    await api.delete(`/api/v1/documents/samples/${id}`);
    if (selectedId === id) setSelectedId(null);
    await refresh();
  }

  async function upload(file: File) {
    setUploading(true);
    setErr(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (uploadTags.trim()) form.append("tags", uploadTags.trim());
      const res = await fetch(apiUrl("/api/v1/documents/samples/upload"), {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = (body && body.detail) || `HTTP ${res.status}`;
        throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
      }
      const s: WritingSample = await res.json();
      setUploadTags("");
      setSelectedId(s.id);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  const selected = samples.find((s) => s.id === selectedId) ?? null;

  return (
    <PageShell
      title="Writing Samples Library"
      subtitle="Your own writing — the reference corpus the humanizer will use to rewrite AI output in your voice."
    >
      {err ? <div className="jsp-card p-4 text-sm text-corp-danger">{err}</div> : null}

      <div className="jsp-card p-4 space-y-3">
        <div className="flex flex-wrap gap-3 items-end justify-between">
          <div className="min-w-0">
            <h3 className="text-sm uppercase tracking-wider text-corp-muted">
              Add a sample
            </h3>
            <p className="text-[11px] text-corp-muted mt-1">
              Paste something you wrote, or upload a .txt / .md file (up to 5 MB).
              Tag each sample so the humanizer can pick matching tones later —
              e.g. <code>blog</code>, <code>email</code>, <code>cover-letter</code>.
            </p>
          </div>
          <div className="flex gap-2 items-end">
            <div>
              <label className="jsp-label">Tags for upload</label>
              <input
                className="jsp-input"
                value={uploadTags}
                onChange={(e) => setUploadTags(e.target.value)}
                placeholder="blog, technical"
                disabled={uploading}
              />
            </div>
            <label
              className={`jsp-btn-ghost cursor-pointer inline-flex ${
                uploading ? "opacity-50 pointer-events-none" : ""
              }`}
            >
              {uploading ? "Uploading..." : "Upload .txt/.md"}
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.md,text/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload(f);
                }}
              />
            </label>
            <button
              className="jsp-btn-primary"
              onClick={() => setEditing("new")}
              disabled={uploading}
            >
              + Paste new
            </button>
          </div>
        </div>
      </div>

      {editing ? (
        <div className="jsp-card p-4 mt-3">
          <SampleForm
            initial={editing === "new" ? null : editing}
            onCancel={() => setEditing(null)}
            onSaved={(s) => {
              setEditing(null);
              setSelectedId(s.id);
              refresh();
            }}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted mt-4">Loading...</p>
      ) : samples.length === 0 ? (
        <div className="jsp-card p-6 mt-4 text-sm text-corp-muted">
          No writing samples yet. Paste or upload one above.
        </div>
      ) : (
        <div className="grid grid-cols-[280px_1fr] gap-3 mt-4">
          <ul className="space-y-1.5">
            {samples.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(s.id)}
                  className={`w-full text-left jsp-card p-3 transition-colors ${
                    selectedId === s.id
                      ? "border-corp-accent"
                      : "hover:border-corp-accent/40"
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm truncate">{s.title}</span>
                    <span className="text-[10px] text-corp-muted">
                      {s.word_count ?? "?"}w
                    </span>
                  </div>
                  {s.tags && s.tags.length > 0 ? (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {s.tags.map((t) => (
                        <span
                          key={t}
                          className="text-[10px] px-1.5 py-0 rounded bg-corp-surface2 border border-corp-border text-corp-muted"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <div className="text-[10px] text-corp-muted mt-1">
                    {s.source ?? "—"} · {new Date(s.created_at).toLocaleDateString()}
                  </div>
                </button>
              </li>
            ))}
          </ul>
          <div>
            {selected ? (
              <div className="jsp-card p-4 space-y-3">
                <div className="flex items-start justify-between gap-2 flex-wrap">
                  <div>
                    <h3 className="text-base font-semibold">{selected.title}</h3>
                    <div className="text-[11px] text-corp-muted">
                      {selected.word_count ?? "?"} words · {selected.source ?? "—"} ·{" "}
                      {new Date(selected.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      className="jsp-btn-ghost text-xs"
                      onClick={() => setEditing(selected)}
                    >
                      Edit
                    </button>
                    <button
                      className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                      onClick={() => remove(selected.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                <pre className="text-sm whitespace-pre-wrap font-mono bg-corp-surface2 border border-corp-border p-4 rounded overflow-x-auto">
                  {selected.content_md}
                </pre>
              </div>
            ) : (
              <div className="jsp-card p-6 text-sm text-corp-muted">
                Pick a sample on the left.
              </div>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}

function SampleForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial: WritingSample | null;
  onCancel: () => void;
  onSaved: (s: WritingSample) => void;
}) {
  const [title, setTitle] = useState(initial?.title ?? "");
  const [content, setContent] = useState(initial?.content_md ?? "");
  const [tagsText, setTagsText] = useState((initial?.tags ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) {
      setErr("Title and content are required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const tags = tagsText
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const payload = {
        title: title.trim(),
        content_md: content,
        tags: tags.length ? tags : null,
        source: initial?.source ?? "pasted",
      };
      const saved = initial
        ? await api.put<WritingSample>(`/api/v1/documents/samples/${initial.id}`, payload)
        : await api.post<WritingSample>("/api/v1/documents/samples", payload);
      onSaved(saved);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Title</label>
          <input
            className="jsp-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Blog post about distributed systems"
          />
        </div>
        <div>
          <label className="jsp-label">Tags (comma-separated)</label>
          <input
            className="jsp-input"
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
            placeholder="blog, technical, conversational"
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Content</label>
          <textarea
            className="jsp-input font-mono min-h-[280px]"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste the writing sample here…"
          />
        </div>
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "Saving..." : initial ? "Save" : "Create"}
        </button>
      </div>
    </form>
  );
}
