"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, apiUrl, ApiError } from "@/lib/api";
import {
  DOC_TYPES,
  type DocType,
  type GeneratedDocument,
  type TrackedJobSummary,
} from "@/lib/types";

type DocFilter = "all" | DocType;

export default function StudioPage() {
  const router = useRouter();
  const [docs, setDocs] = useState<GeneratedDocument[]>([]);
  const [jobs, setJobs] = useState<TrackedJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<DocFilter>("all");
  const [filterJob, setFilterJob] = useState<number | "all">("all");
  const [filterTag, setFilterTag] = useState<string | "all">("all");
  const [creating, setCreating] = useState(false);
  // Multi-select state for batch humanize. Keyed by doc id; cleared on
  // refresh so a stale set never lingers across loads.
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchMsg, setBatchMsg] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const [d, j] = await Promise.all([
        api.get<GeneratedDocument[]>("/api/v1/documents"),
        api.get<TrackedJobSummary[]>("/api/v1/jobs"),
      ]);
      setDocs(d);
      setJobs(j);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load documents (HTTP ${e.status}).`
          : "Failed to load documents.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const jobById = useMemo(
    () => new Map(jobs.map((j) => [j.id, j])),
    [jobs],
  );

  const filtered = useMemo(
    () =>
      docs.filter((d) => {
        if (filterType !== "all" && d.doc_type !== filterType) return false;
        if (filterJob !== "all" && d.tracked_job_id !== filterJob) return false;
        if (filterTag !== "all" && !(d.tags ?? []).includes(filterTag)) return false;
        return true;
      }),
    [docs, filterType, filterJob, filterTag],
  );

  const countsByType = useMemo(() => {
    const map = new Map<string, number>();
    for (const d of docs) map.set(d.doc_type, (map.get(d.doc_type) ?? 0) + 1);
    return map;
  }, [docs]);

  const allTags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const d of docs) {
      for (const t of d.tags ?? []) {
        counts.set(t, (counts.get(t) ?? 0) + 1);
      }
    }
    return [...counts.entries()].sort((a, b) =>
      b[1] - a[1] || a[0].localeCompare(b[0]),
    );
  }, [docs]);

  async function setTags(id: number, tags: string[]) {
    const updated = await api.put<GeneratedDocument>(
      `/api/v1/documents/${id}`,
      { tags },
    );
    setDocs((prev) => prev.map((d) => (d.id === id ? updated : d)));
  }

  function toggleSelected(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllVisible() {
    setSelectedIds((prev) => {
      const visibleIds = filtered.map((d) => d.id);
      const allSelected = visibleIds.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allSelected) {
        for (const id of visibleIds) next.delete(id);
      } else {
        for (const id of visibleIds) next.add(id);
      }
      return next;
    });
  }

  // Skip rows that aren't humanizable: uploads with no extracted text, or
  // already-humanized versions (humanize is idempotent-ish, but the user
  // probably means "the ones that aren't done yet"). Show a warning if the
  // selection has skip-eligible rows so the user can adjust if they meant
  // those too.
  async function batchHumanize() {
    const targets = filtered.filter(
      (d) =>
        selectedIds.has(d.id) &&
        !!d.content_md &&
        d.content_md.trim().length > 0 &&
        !d.humanized,
    );
    const skipped =
      [...selectedIds].length - targets.length;
    if (targets.length === 0) {
      setBatchMsg(
        skipped > 0
          ? "Nothing to humanize — all selected rows are uploads with no text or already humanized."
          : "Nothing selected.",
      );
      return;
    }
    setBatchRunning(true);
    setBatchMsg(null);
    try {
      const results = await Promise.allSettled(
        targets.map((d) =>
          api.post<GeneratedDocument>(`/api/v1/documents/${d.id}/humanize`, {}),
        ),
      );
      const ok = results.filter((r) => r.status === "fulfilled").length;
      const fail = results.length - ok;
      const skipNote = skipped > 0 ? `, skipped ${skipped}` : "";
      setBatchMsg(
        fail > 0
          ? `Queued ${ok} of ${results.length} (${fail} failed)${skipNote}. Check Studio in a moment.`
          : `Queued ${ok} humanize task${ok === 1 ? "" : "s"}${skipNote}. They'll appear here as new versions when done.`,
      );
      setSelectedIds(new Set());
      await refresh();
    } catch (e) {
      setBatchMsg(
        e instanceof ApiError
          ? `Batch humanize failed (HTTP ${e.status}).`
          : "Batch humanize failed.",
      );
    } finally {
      setBatchRunning(false);
    }
  }

  async function removeDoc(id: number) {
    if (!confirm("Delete this document?")) return;
    await api.delete(`/api/v1/documents/${id}`);
    await refresh();
  }

  return (
    <PageShell
      title="Document Studio"
      subtitle="Every resume, cover letter, and uploaded file in one place."
      actions={
        <button
          className="jsp-btn-primary"
          onClick={() => setCreating(true)}
          disabled={creating}
        >
          + New document
        </button>
      }
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger">{err}</div>
      ) : null}

      {creating ? (
        <div className="jsp-card p-4 mb-3">
          <NewDocumentForm
            jobs={jobs}
            onCancel={() => setCreating(false)}
            onCreated={(d) => {
              setCreating(false);
              router.push(`/studio/${d.id}`);
            }}
          />
        </div>
      ) : null}

      <div className="jsp-card p-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="jsp-label">Filter by type</label>
            <select
              className="jsp-input"
              value={filterType}
              onChange={(e) => setFilterType(e.target.value as DocFilter)}
            >
              <option value="all">All types ({docs.length})</option>
              {DOC_TYPES.map((t) => {
                const n = countsByType.get(t) ?? 0;
                if (n === 0) return null;
                return (
                  <option key={t} value={t}>
                    {t.replace(/_/g, " ")} ({n})
                  </option>
                );
              })}
            </select>
          </div>
          <div>
            <label className="jsp-label">Filter by job</label>
            <select
              className="jsp-input"
              value={filterJob}
              onChange={(e) =>
                setFilterJob(e.target.value === "all" ? "all" : Number(e.target.value))
              }
            >
              <option value="all">All jobs</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title}
                  {j.organization_name ? ` · ${j.organization_name}` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        {allTags.length > 0 ? (
          <div className="mt-3">
            <label className="jsp-label">Filter by tag</label>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setFilterTag("all")}
                className={`px-2 py-0.5 rounded-md text-[10px] uppercase tracking-wider border ${
                  filterTag === "all"
                    ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
                    : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text"
                }`}
              >
                All
              </button>
              {allTags.map(([tag, n]) => (
                <button
                  key={tag}
                  type="button"
                  onClick={() => setFilterTag(filterTag === tag ? "all" : tag)}
                  className={`px-2 py-0.5 rounded-md text-[10px] uppercase tracking-wider border ${
                    filterTag === tag
                      ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
                      : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text"
                  }`}
                >
                  #{tag}
                  <span className="ml-1 opacity-60">{n}</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {selectedIds.size > 0 ? (
        <div className="jsp-card p-3 mt-3 flex flex-wrap gap-2 items-center">
          <span className="text-xs text-corp-muted">
            {selectedIds.size} selected
          </span>
          <button
            type="button"
            className="jsp-btn-primary text-xs"
            onClick={batchHumanize}
            disabled={batchRunning}
            title="Run humanize against every selected doc that has text and isn't already humanized"
          >
            {batchRunning ? "Queuing…" : "Humanize all"}
          </button>
          <button
            type="button"
            className="jsp-btn-ghost text-xs"
            onClick={() => setSelectedIds(new Set())}
            disabled={batchRunning}
          >
            Clear
          </button>
          {batchMsg ? (
            <span className="text-[11px] text-corp-muted ml-2">{batchMsg}</span>
          ) : null}
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted mt-4">Loading...</p>
      ) : filtered.length === 0 ? (
        <div className="jsp-card p-6 mt-4 text-sm text-corp-muted">
          No documents match those filters.
          {docs.length === 0 ? (
            <>
              {" "}
              Open any job in the{" "}
              <Link href="/jobs" className="text-corp-accent hover:underline">
                Job Tracker
              </Link>{" "}
              and use the Documents tab to write or upload your first one.
            </>
          ) : null}
        </div>
      ) : (
        <ul className="jsp-card divide-y divide-corp-border mt-4">
          <li className="flex items-center gap-3 py-2 px-4 bg-corp-surface2 text-[10px] uppercase tracking-wider text-corp-muted">
            <input
              type="checkbox"
              className="accent-corp-accent"
              aria-label="Select all visible documents"
              checked={
                filtered.length > 0 &&
                filtered.every((d) => selectedIds.has(d.id))
              }
              ref={(el) => {
                if (el) {
                  const count = filtered.filter((d) =>
                    selectedIds.has(d.id),
                  ).length;
                  el.indeterminate = count > 0 && count < filtered.length;
                }
              }}
              onChange={toggleSelectAllVisible}
            />
            <span>Select</span>
          </li>
          {filtered.map((d) => (
            <StudioListRow
              key={d.id}
              doc={d}
              job={
                d.tracked_job_id ? jobById.get(d.tracked_job_id) ?? null : null
              }
              onDelete={() => removeDoc(d.id)}
              onTagsChange={(next) => setTags(d.id, next)}
              onTagClick={(t) => setFilterTag(filterTag === t ? "all" : t)}
              selected={selectedIds.has(d.id)}
              onToggleSelected={() => toggleSelected(d.id)}
            />
          ))}
        </ul>
      )}
    </PageShell>
  );
}

function StudioListRow({
  doc,
  job,
  onDelete,
  onTagsChange,
  onTagClick,
  selected,
  onToggleSelected,
}: {
  doc: GeneratedDocument;
  job: TrackedJobSummary | null;
  onDelete: () => void;
  onTagsChange: (next: string[]) => void | Promise<void>;
  onTagClick: (tag: string) => void;
  selected: boolean;
  onToggleSelected: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  async function commitAdd() {
    const t = draft.trim().toLowerCase();
    setAdding(false);
    setDraft("");
    if (!t) return;
    const next = [...new Set([...(doc.tags ?? []), t])];
    try {
      await onTagsChange(next);
    } catch {
      /* non-fatal */
    }
  }

  async function removeTag(t: string) {
    try {
      await onTagsChange((doc.tags ?? []).filter((x) => x !== t));
    } catch {
      /* non-fatal */
    }
  }

  const structured = (doc.content_structured ?? null) as
    | {
        original_filename?: string | null;
        stored_path?: string | null;
        mime_type?: string | null;
        size_bytes?: number | null;
      }
    | null;

  const isUpload = !!structured?.stored_path;
  const fileUrl = isUpload ? apiUrl(`/api/v1/documents/${doc.id}/file`) : null;
  const downloadUrl = isUpload
    ? apiUrl(`/api/v1/documents/${doc.id}/file?download=1`)
    : null;

  const editorHref = `/studio/${doc.id}`;

  const sizeLabel =
    structured?.size_bytes != null
      ? structured.size_bytes > 1_000_000
        ? `${(structured.size_bytes / 1_000_000).toFixed(1)} MB`
        : `${Math.max(1, Math.round(structured.size_bytes / 1024))} KB`
      : null;

  const subline = [
    isUpload ? "uploaded" : "written",
    job ? `${job.title}${job.organization_name ? ` · ${job.organization_name}` : ""}` : null,
    structured?.original_filename,
    sizeLabel,
    new Date(doc.created_at).toLocaleString(),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li
      className={`flex items-center gap-3 py-2 px-4 ${selected ? "bg-corp-accent/10" : ""}`}
    >
      <input
        type="checkbox"
        className="accent-corp-accent shrink-0"
        checked={selected}
        onChange={onToggleSelected}
        aria-label={`Select ${doc.title}`}
      />
      <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border shrink-0">
        {doc.doc_type.replace(/_/g, " ")}
      </span>
      <span className="text-[10px] text-corp-muted shrink-0 w-8">
        v{doc.version}
      </span>
      <div className="flex-1 min-w-0">
        <a
          href={editorHref}
          className="text-sm truncate hover:text-corp-accent block"
        >
          {doc.title}
        </a>
        <div className="text-[11px] text-corp-muted truncate">{subline}</div>
        <div className="flex flex-wrap gap-1 mt-1 items-center">
          {(doc.tags ?? []).map((t) => (
            <span
              key={t}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border bg-corp-surface2 text-corp-muted border-corp-border"
            >
              <button
                type="button"
                onClick={() => onTagClick(t)}
                className="hover:text-corp-accent"
                title={`Filter by #${t}`}
              >
                #{t}
              </button>
              <button
                type="button"
                onClick={() => removeTag(t)}
                className="opacity-50 hover:opacity-100 hover:text-corp-danger"
                title="Remove tag"
                aria-label={`Remove tag ${t}`}
              >
                ×
              </button>
            </span>
          ))}
          {adding ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitAdd}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitAdd();
                } else if (e.key === "Escape") {
                  setAdding(false);
                  setDraft("");
                }
              }}
              placeholder="tag"
              className="text-[10px] px-1.5 py-0.5 bg-corp-surface2 border border-corp-border rounded uppercase tracking-wider text-corp-text outline-none focus:border-corp-accent w-20"
            />
          ) : (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="text-[10px] px-1.5 py-0.5 rounded border border-dashed border-corp-border text-corp-muted hover:text-corp-accent hover:border-corp-accent uppercase tracking-wider"
              title="Add tag"
            >
              + tag
            </button>
          )}
        </div>
      </div>
      <div className="flex gap-1.5 shrink-0">
        <a className="jsp-btn-ghost text-xs" href={editorHref}>
          Editor
        </a>
        {fileUrl ? (
          <a
            className="jsp-btn-ghost text-xs"
            href={fileUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open
          </a>
        ) : null}
        {downloadUrl ? (
          <a className="jsp-btn-ghost text-xs" href={downloadUrl}>
            Download
          </a>
        ) : null}
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

function NewDocumentForm({
  jobs,
  onCancel,
  onCreated,
}: {
  jobs: TrackedJobSummary[];
  onCancel: () => void;
  onCreated: (doc: GeneratedDocument) => void;
}) {
  const [docType, setDocType] = useState<DocType>("resume");
  const [title, setTitle] = useState("");
  const [trackedJobId, setTrackedJobId] = useState<number | "none">("none");
  const [contentMd, setContentMd] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setErr("Title is required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const doc = await api.post<GeneratedDocument>("/api/v1/documents", {
        doc_type: docType,
        title: title.trim(),
        tracked_job_id: trackedJobId === "none" ? null : trackedJobId,
        content_md: contentMd || null,
      });
      onCreated(doc);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Create failed (HTTP ${e.status}).` : "Create failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <h3 className="text-sm uppercase tracking-wider text-corp-muted">
        New document
      </h3>
      <p className="text-[11px] text-corp-muted">
        Starts a blank document you can write yourself. For AI-assisted
        drafting, open a job and use the Documents tab&apos;s Write button instead.
      </p>
      <div className="grid grid-cols-[160px_1fr] gap-3">
        <div>
          <label className="jsp-label">Type</label>
          <select
            className="jsp-input"
            value={docType}
            onChange={(e) => setDocType(e.target.value as DocType)}
            disabled={saving}
          >
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Title</label>
          <input
            className="jsp-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Base resume · 2026"
            disabled={saving}
          />
        </div>
      </div>
      <div>
        <label className="jsp-label">Attach to job (optional)</label>
        <select
          className="jsp-input"
          value={trackedJobId}
          onChange={(e) =>
            setTrackedJobId(
              e.target.value === "none" ? "none" : Number(e.target.value),
            )
          }
          disabled={saving}
        >
          <option value="none">— Unaffiliated (general document)</option>
          {jobs.map((j) => (
            <option key={j.id} value={j.id}>
              {j.title}
              {j.organization_name ? ` · ${j.organization_name}` : ""}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="jsp-label">Starter content (optional)</label>
        <textarea
          className="jsp-input font-mono text-sm min-h-[140px]"
          value={contentMd}
          onChange={(e) => setContentMd(e.target.value)}
          placeholder="# Heading\n\nLeave blank and write in the editor, or paste seed text here."
          disabled={saving}
        />
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "Creating..." : "Create & open editor"}
        </button>
      </div>
    </form>
  );
}
