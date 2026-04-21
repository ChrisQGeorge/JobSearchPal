"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, ApiError } from "@/lib/api";
import {
  JOB_STATUSES,
  type JobFetchQueueItem,
  type JobFetchQueueState,
  type JobStatus,
} from "@/lib/types";

const STATE_STYLES: Record<JobFetchQueueState, string> = {
  queued: "bg-corp-surface2 text-corp-muted border-corp-border",
  processing: "bg-sky-500/25 text-sky-300 border-sky-500/40 animate-pulse",
  done: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  error: "bg-corp-danger/20 text-corp-danger border-corp-danger/40",
};

type Props = {
  // Called after a queue item transitions to "done" with a created_tracked_job_id
  // so the parent list can refresh.
  onJobCreated?: () => void;
};

export function FetchQueuePanel({ onJobCreated }: Props) {
  const [items, setItems] = useState<JobFetchQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [url, setUrl] = useState("");
  const [desiredStatus, setDesiredStatus] = useState<JobStatus | "">("");
  const [desiredDateApplied, setDesiredDateApplied] = useState("");
  const [desiredDateClosed, setDesiredDateClosed] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seenDoneIds = useRef<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const data = await api.get<JobFetchQueueItem[]>("/api/v1/jobs/queue");
      setItems(data);
      // Notify parent when new "done" items appear since last poll.
      for (const it of data) {
        if (it.state === "done" && !seenDoneIds.current.has(it.id)) {
          seenDoneIds.current.add(it.id);
          onJobCreated?.();
        }
      }
    } catch {
      /* non-fatal; try again next poll */
    } finally {
      setLoading(false);
    }
  }, [onJobCreated]);

  useEffect(() => {
    refresh();
    // Poll every 3s while any item is queued/processing, every 15s otherwise.
    const interval = setInterval(() => {
      const active = items.some((i) => i.state === "queued" || i.state === "processing");
      if (active) refresh();
      else if (expanded) refresh();
    }, 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, items.map((i) => i.state).join(","), expanded]);

  async function enqueue(e: React.FormEvent) {
    e.preventDefault();
    const u = url.trim();
    if (!u) return;
    setAdding(true);
    setError(null);
    try {
      await api.post<JobFetchQueueItem>("/api/v1/jobs/queue", {
        url: u,
        desired_status: desiredStatus || null,
        desired_date_applied: desiredDateApplied || null,
        desired_date_closed: desiredDateClosed || null,
      });
      setUrl("");
      await refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Enqueue failed (HTTP ${err.status}).`
          : "Enqueue failed.",
      );
    } finally {
      setAdding(false);
    }
  }

  async function remove(id: number) {
    await api.delete(`/api/v1/jobs/queue/${id}`);
    await refresh();
  }

  async function retry(id: number) {
    await api.post(`/api/v1/jobs/queue/${id}/retry`);
    await refresh();
  }

  const activeCount = items.filter(
    (i) => i.state === "queued" || i.state === "processing",
  ).length;

  return (
    <section className="jsp-card">
      <header
        className="flex items-center justify-between px-4 py-3 cursor-pointer select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-3">
          <h2 className="text-sm uppercase tracking-wider text-corp-muted">
            Fetch Queue
          </h2>
          {activeCount > 0 ? (
            <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-sky-500/25 text-sky-300 border border-sky-500/40">
              {activeCount} in flight
            </span>
          ) : items.length > 0 ? (
            <span className="text-xs text-corp-muted">{items.length} total</span>
          ) : null}
        </div>
        <button className="jsp-btn-ghost text-xs" type="button">
          {expanded ? "Hide" : "Show"}
        </button>
      </header>

      {expanded ? (
        <div className="border-t border-corp-border px-4 py-3 space-y-3">
          <p className="text-xs text-corp-muted">
            Drop in job-posting URLs — the Companion will cycle through and
            create a TrackedJob for each. Optional preset status / dates apply
            to the created record so you can mark everything as <code>applied</code> up-front.
          </p>

          <form onSubmit={enqueue} className="grid grid-cols-2 gap-2 items-end">
            <div className="col-span-2">
              <label className="jsp-label">Job URL</label>
              <input
                className="jsp-input"
                placeholder="https://..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={adding}
              />
            </div>
            <div>
              <label className="jsp-label">Preset status</label>
              <select
                className="jsp-input"
                value={desiredStatus}
                onChange={(e) => setDesiredStatus(e.target.value as JobStatus | "")}
              >
                <option value="">— (default: watching)</option>
                {JOB_STATUSES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="jsp-label">Preset date applied</label>
              <input
                type="date"
                className="jsp-input"
                value={desiredDateApplied}
                onChange={(e) => setDesiredDateApplied(e.target.value)}
              />
            </div>
            <div>
              <label className="jsp-label">Preset date closed</label>
              <input
                type="date"
                className="jsp-input"
                value={desiredDateClosed}
                onChange={(e) => setDesiredDateClosed(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                className="jsp-btn-primary"
                disabled={adding || !url.trim()}
              >
                {adding ? "..." : "Add to queue"}
              </button>
            </div>
          </form>

          {error ? <div className="text-xs text-corp-danger">{error}</div> : null}

          {loading ? (
            <div className="text-xs text-corp-muted">Loading queue...</div>
          ) : items.length === 0 ? (
            <div className="text-xs text-corp-muted">Queue is empty.</div>
          ) : (
            <ul className="space-y-1.5">
              {items.map((it) => (
                <li
                  key={it.id}
                  className="flex items-start gap-3 py-2 border-t border-corp-border/40 first:border-t-0"
                >
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border shrink-0 mt-0.5 ${STATE_STYLES[it.state]}`}
                  >
                    {it.state}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate">
                      <a
                        href={it.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-corp-accent"
                      >
                        {it.url}
                      </a>
                    </div>
                    <div className="text-[11px] text-corp-muted">
                      {[
                        it.desired_status && `→ ${it.desired_status}`,
                        it.desired_date_applied && `applied ${it.desired_date_applied}`,
                        it.desired_date_closed && `closed ${it.desired_date_closed}`,
                        it.attempts > 0 && `${it.attempts} attempt${it.attempts === 1 ? "" : "s"}`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {it.error_message ? (
                      <div className="text-xs text-corp-danger mt-0.5">
                        {it.error_message}
                      </div>
                    ) : null}
                    {it.created_tracked_job_id ? (
                      <a
                        href={`/jobs/${it.created_tracked_job_id}`}
                        className="text-xs text-corp-accent hover:underline"
                      >
                        → Open job #{it.created_tracked_job_id}
                      </a>
                    ) : null}
                  </div>
                  <div className="flex gap-1 shrink-0">
                    {it.state === "error" ? (
                      <button
                        type="button"
                        className="jsp-btn-ghost text-xs"
                        onClick={() => retry(it.id)}
                      >
                        Retry
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                      onClick={() => remove(it.id)}
                      title="Remove from queue"
                    >
                      ×
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}

/** Fire-and-forget download trigger for the Excel template. */
export async function downloadExcelTemplate() {
  const res = await fetch(apiUrl("/api/v1/jobs/import-template.xlsx"), {
    credentials: "include",
  });
  if (!res.ok) throw new Error(`Template download failed (${res.status})`);
  const blob = await res.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "job-search-pal-template.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

/** Upload an .xlsx file to the bulk-import endpoint. */
export async function importExcel(file: File): Promise<{
  created_count: number;
  skipped_count: number;
  errors: { row: number; error: string }[];
}> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(apiUrl("/api/v1/jobs/import"), {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Import failed (HTTP ${res.status}): ${text.slice(0, 300)}`);
  }
  return res.json();
}

/** Fire-and-forget download trigger for the minimal queue-import template. */
export async function downloadQueueTemplate() {
  const res = await fetch(apiUrl("/api/v1/jobs/queue-import-template.xlsx"), {
    credentials: "include",
  });
  if (!res.ok) throw new Error(`Template download failed (${res.status})`);
  const blob = await res.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "job-search-pal-queue-template.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

/** Upload an .xlsx file to the queue-import endpoint. Each row becomes a
 *  JobFetchQueue entry; the worker then visits the URL and creates the
 *  TrackedJob in the background. */
export async function importQueueExcel(file: File): Promise<{
  enqueued_count: number;
  skipped_count: number;
  errors: { row: number; error: string }[];
}> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(apiUrl("/api/v1/jobs/queue-import"), {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Queue import failed (HTTP ${res.status}): ${text.slice(0, 300)}`);
  }
  return res.json();
}
