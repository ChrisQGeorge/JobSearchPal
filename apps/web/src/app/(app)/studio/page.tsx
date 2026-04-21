"use client";

import Link from "next/link";
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
  const [docs, setDocs] = useState<GeneratedDocument[]>([]);
  const [jobs, setJobs] = useState<TrackedJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<DocFilter>("all");
  const [filterJob, setFilterJob] = useState<number | "all">("all");

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
        return true;
      }),
    [docs, filterType, filterJob],
  );

  const countsByType = useMemo(() => {
    const map = new Map<string, number>();
    for (const d of docs) map.set(d.doc_type, (map.get(d.doc_type) ?? 0) + 1);
    return map;
  }, [docs]);

  async function removeDoc(id: number) {
    if (!confirm("Delete this document?")) return;
    await api.delete(`/api/v1/documents/${id}`);
    await refresh();
  }

  return (
    <PageShell
      title="Document Studio"
      subtitle="Every resume, cover letter, and uploaded file in one place."
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger">{err}</div>
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
      </div>

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
          {filtered.map((d) => (
            <StudioListRow
              key={d.id}
              doc={d}
              job={
                d.tracked_job_id ? jobById.get(d.tracked_job_id) ?? null : null
              }
              onDelete={() => removeDoc(d.id)}
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
}: {
  doc: GeneratedDocument;
  job: TrackedJobSummary | null;
  onDelete: () => void;
}) {
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
    <li className="flex items-center gap-3 py-2 px-4">
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
