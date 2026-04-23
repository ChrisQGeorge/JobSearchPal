"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, apiUrl, ApiError } from "@/lib/api";
import {
  JOB_STATUSES,
  type JobFetchQueueItem,
  type JobFetchQueueState,
  type JobStatus,
} from "@/lib/types";

type Filter = "active" | "waiting" | "done" | "error" | "all";

// Unified activity row — includes both persistent fetch-queue items and
// in-memory Companion task rows. See ActivityRowOut in jobs.py.
type ActivityRow = {
  id: string;                 // "fetch:<id>" or "task:<source>:<item_id>"
  kind: "fetch" | "companion";
  source: string;
  label: string;
  status: string;             // queued | processing | running | done | error
  started_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
  last_text: string | null;
  last_tool: string | null;
  error: string | null;
  // fetch-specific
  fetch_queue_id: number | null;
  url: string | null;
  attempts: number | null;
  resume_after: string | null;
  tracked_job_id: number | null;
  // companion-specific
  cost_usd: number | null;
  duration_ms: number | null;
  num_turns: number | null;
};

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-corp-surface2 text-corp-muted border-corp-border",
  running: "bg-sky-500/25 text-sky-300 border-sky-500/40 animate-pulse",
  processing: "bg-sky-500/25 text-sky-300 border-sky-500/40 animate-pulse",
  done: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  error: "bg-corp-danger/20 text-corp-danger border-corp-danger/40",
};

const WAITING_STYLE =
  "bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40";

function isWaiting(it: ActivityRow): boolean {
  return !!it.resume_after && new Date(it.resume_after) > new Date();
}

function isActive(it: ActivityRow): boolean {
  return (
    !isWaiting(it) &&
    (it.status === "queued" ||
      it.status === "processing" ||
      it.status === "running")
  );
}

export default function QueuePage() {
  const [items, setItems] = useState<ActivityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("active");
  const [url, setUrl] = useState("");
  const [desiredStatus, setDesiredStatus] = useState<JobStatus | "">("");
  const [desiredApplied, setDesiredApplied] = useState("");
  const [desiredPosted, setDesiredPosted] = useState("");
  const [adding, setAdding] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const taskStreamRef = useRef<EventSource | null>(null);

  async function refresh() {
    try {
      const data = await api.get<ActivityRow[]>("/api/v1/jobs/activity");
      // Backend already sorts most-recent-first.
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

  // Live task-row updates from the server. Merges in-place by id so we
  // don't need a full refresh between polls.
  useEffect(() => {
    const es = new EventSource(apiUrl("/api/v1/jobs/activity/stream"));
    taskStreamRef.current = es;
    es.onmessage = (evt) => {
      try {
        const raw = JSON.parse(evt.data);
        if (raw.kind !== "task_update") return;
        const row: ActivityRow = {
          id: `task:${raw.key}`,
          kind: "companion",
          source: raw.source,
          label: raw.label || raw.source,
          status: raw.status || "running",
          started_at: raw.started_at ?? null,
          updated_at: raw.updated_at ?? null,
          finished_at: raw.finished_at ?? null,
          last_text: raw.last_text ?? null,
          last_tool: raw.last_tool ?? null,
          error: raw.error ?? null,
          fetch_queue_id: null,
          url: null,
          attempts: null,
          resume_after: null,
          tracked_job_id: null,
          cost_usd: raw.cost_usd ?? null,
          duration_ms: raw.duration_ms ?? null,
          num_turns: raw.num_turns ?? null,
        };
        setItems((prev) => {
          const without = prev.filter((p) => p.id !== row.id);
          const next = [row, ...without];
          next.sort((a, b) => {
            const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0;
            const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0;
            return tb - ta;
          });
          return next;
        });
      } catch {
        /* non-fatal */
      }
    };
    es.onerror = () => {
      /* auto-reconnect from EventSource; nothing to do */
    };
    return () => {
      es.close();
      taskStreamRef.current = null;
    };
  }, []);

  // Poll on a schedule: 3s when anything is actively moving, else 15s.
  // The SSE covers companion tasks; polling is still needed for fetch rows,
  // since JobFetchQueue's state transitions aren't funneled through the bus
  // in every path.
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    const active = items.some(isActive);
    const ms = active ? 3000 : 15000;
    pollRef.current = setInterval(refresh, ms);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.map((i) => i.status + (i.resume_after ?? "")).join(",")]);

  async function enqueue(e: React.FormEvent) {
    e.preventDefault();
    const u = url.trim();
    if (!u) return;
    setAdding(true);
    setErr(null);
    try {
      await api.post<JobFetchQueueItem>("/api/v1/jobs/queue", {
        url: u,
        desired_status: desiredStatus || null,
        desired_date_applied: desiredApplied || null,
        desired_date_posted: desiredPosted || null,
      });
      setUrl("");
      await refresh();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Enqueue failed (HTTP ${e.status}).` : "Enqueue failed.",
      );
    } finally {
      setAdding(false);
    }
  }

  async function retry(fetchQueueId: number) {
    await api.post(`/api/v1/jobs/queue/${fetchQueueId}/retry`);
    await refresh();
  }

  async function remove(fetchQueueId: number) {
    if (!confirm("Remove this queue item?")) return;
    await api.delete(`/api/v1/jobs/queue/${fetchQueueId}`);
    await refresh();
  }

  const counts = useMemo(() => {
    let active = 0;
    let waiting = 0;
    let done = 0;
    let errored = 0;
    let processing = 0;
    for (const it of items) {
      if (isWaiting(it)) waiting++;
      else if (it.status === "processing" || it.status === "running") {
        processing++;
        active++;
      } else if (it.status === "queued") active++;
      else if (it.status === "done") done++;
      else if (it.status === "error") errored++;
    }
    return { active, waiting, done, errored, processing, total: items.length };
  }, [items]);

  const visible = useMemo<ActivityRow[]>(() => {
    switch (filter) {
      case "all":
        return items;
      case "active":
        return items.filter(isActive);
      case "waiting":
        return items.filter(isWaiting);
      case "done":
        return items.filter((i) => i.status === "done");
      case "error":
        return items.filter((i) => i.status === "error");
      default:
        return items;
    }
  }, [items, filter]);

  // Soonest upcoming resume, for the "next resume in N min" hint.
  const nextResume = useMemo(() => {
    const now = Date.now();
    let best: number | null = null;
    for (const it of items) {
      if (!it.resume_after) continue;
      const t = new Date(it.resume_after).getTime();
      if (t > now && (best === null || t < best)) best = t;
    }
    return best;
  }, [items]);

  return (
    <PageShell
      title="Companion Activity"
      subtitle="URLs waiting to become TrackedJobs, plus a live feed of every Claude task the app fires. Rate-limited items back off and resume automatically."
    >
      <section className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        <Kpi
          label="Active"
          value={counts.active}
          sub={
            counts.processing > 0
              ? `${counts.processing} processing now`
              : counts.active === 0
                ? "Idle"
                : "Ready to run"
          }
          href={counts.active > 0 ? undefined : undefined}
          tone={counts.processing > 0 ? "primary" : undefined}
        />
        <Kpi
          label="Waiting"
          value={counts.waiting}
          sub={
            counts.waiting > 0 && nextResume
              ? `Next: ${new Date(nextResume).toLocaleTimeString()}`
              : "None cooling down"
          }
          tone={counts.waiting > 0 ? "warn" : undefined}
        />
        <Kpi
          label="Done"
          value={counts.done}
          sub={counts.done > 0 ? "Created tracked jobs" : "—"}
          tone={counts.done > 0 ? "good" : undefined}
        />
        <Kpi
          label="Errored"
          value={counts.errored}
          sub={counts.errored > 0 ? "Needs attention" : "—"}
          tone={counts.errored > 0 ? "danger" : undefined}
        />
        <Kpi
          label="Total"
          value={counts.total}
          sub={counts.total === 0 ? "Queue is empty" : "All rows ever"}
        />
      </section>

      <form
        onSubmit={enqueue}
        className="jsp-card p-4 mb-4 grid grid-cols-[1fr_180px_180px_180px_auto] gap-2 items-end"
      >
        <div>
          <label className="jsp-label">New URL</label>
          <input
            className="jsp-input"
            placeholder="https://…"
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
            disabled={adding}
          >
            <option value="">— (default: watching)</option>
            {JOB_STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Date applied</label>
          <input
            type="date"
            className="jsp-input"
            value={desiredApplied}
            onChange={(e) => setDesiredApplied(e.target.value)}
            disabled={adding}
          />
        </div>
        <div>
          <label className="jsp-label">Date posted</label>
          <input
            type="date"
            className="jsp-input"
            value={desiredPosted}
            onChange={(e) => setDesiredPosted(e.target.value)}
            disabled={adding}
          />
        </div>
        <button
          type="submit"
          className="jsp-btn-primary"
          disabled={adding || !url.trim()}
        >
          {adding ? "…" : "Queue"}
        </button>
      </form>

      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <FilterPill
          active={filter === "active"}
          count={counts.active}
          label="Active"
          onClick={() => setFilter("active")}
        />
        <FilterPill
          active={filter === "waiting"}
          count={counts.waiting}
          label="Waiting"
          tone="warn"
          onClick={() => setFilter("waiting")}
        />
        <FilterPill
          active={filter === "done"}
          count={counts.done}
          label="Done"
          tone="good"
          onClick={() => setFilter("done")}
        />
        <FilterPill
          active={filter === "error"}
          count={counts.errored}
          label="Errored"
          tone="danger"
          onClick={() => setFilter("error")}
        />
        <FilterPill
          active={filter === "all"}
          count={counts.total}
          label="All"
          onClick={() => setFilter("all")}
        />
        <button
          type="button"
          className="jsp-btn-ghost text-xs ml-auto"
          onClick={refresh}
          disabled={loading}
        >
          {loading ? "…" : "Refresh"}
        </button>
      </div>

      {err ? (
        <div className="jsp-card p-3 mb-3 text-sm text-corp-danger">{err}</div>
      ) : null}

      <LiveStreamPanel />


      {visible.length === 0 ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          {filter === "active"
            ? "No active items. Queue a URL above to get started."
            : "No items in this view."}
        </div>
      ) : (
        <ul className="jsp-card divide-y divide-corp-border overflow-hidden">
          {visible.map((it) => (
            <QueueRow
              key={it.id}
              item={it}
              onRetry={() => {
                if (it.fetch_queue_id != null) void retry(it.fetch_queue_id);
              }}
              onRemove={() => {
                if (it.fetch_queue_id != null) void remove(it.fetch_queue_id);
              }}
            />
          ))}
        </ul>
      )}
    </PageShell>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone,
  href,
}: {
  label: string;
  value: number | string;
  sub?: string;
  tone?: "good" | "warn" | "danger" | "primary";
  href?: string;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-300"
      : tone === "warn"
        ? "text-corp-accent2"
        : tone === "danger"
          ? "text-corp-danger"
          : "text-corp-accent";
  const body = (
    <div className="jsp-card p-4 h-full">
      <div className="text-[10px] uppercase tracking-wider text-corp-muted">
        {label}
      </div>
      <div className={`text-2xl font-semibold mt-1 ${toneClass}`}>{value}</div>
      {sub ? <div className="text-[11px] text-corp-muted mt-0.5">{sub}</div> : null}
    </div>
  );
  return href ? (
    <Link href={href} className="block hover:opacity-90">
      {body}
    </Link>
  ) : (
    body
  );
}

function FilterPill({
  label,
  count,
  active,
  tone,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  tone?: "good" | "warn" | "danger";
  onClick: () => void;
}) {
  const activeClass = active
    ? tone === "good"
      ? "bg-emerald-500/25 text-emerald-300 border-emerald-500/40"
      : tone === "warn"
        ? "bg-corp-accent2/25 text-corp-accent2 border-corp-accent2/40"
        : tone === "danger"
          ? "bg-corp-danger/20 text-corp-danger border-corp-danger/40"
          : "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
    : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-2.5 py-1 rounded-md text-xs uppercase tracking-wider border ${activeClass}`}
    >
      {label} <span className="opacity-70">{count}</span>
    </button>
  );
}

function QueueRow({
  item,
  onRetry,
  onRemove,
}: {
  item: ActivityRow;
  onRetry: () => void;
  onRemove: () => void;
}) {
  const waiting = isWaiting(item);
  const pillClass = waiting
    ? WAITING_STYLE
    : STATUS_STYLES[item.status] ??
      "bg-corp-surface2 text-corp-muted border-corp-border";
  const pillText = waiting ? "waiting" : item.status;

  const resumeIn = item.resume_after
    ? Math.max(0, Math.floor((new Date(item.resume_after).getTime() - Date.now()) / 60000))
    : null;
  // Pretty-format multi-hour waits — "4h 58m" instead of "298 min".
  const resumeInPretty =
    resumeIn == null
      ? null
      : resumeIn >= 60
        ? `${Math.floor(resumeIn / 60)}h ${resumeIn % 60}m`
        : `${resumeIn}m`;

  const srcLabel = SOURCE_LABEL[item.source] ?? item.source.toUpperCase();
  const srcColor =
    SOURCE_COLOR[item.source] ??
    "bg-corp-surface2 text-corp-muted border-corp-border";

  const isCompanion = item.kind === "companion";

  // Cost formatted as $0.0023 if present.
  const costStr =
    item.cost_usd != null
      ? `$${item.cost_usd < 0.01 ? item.cost_usd.toFixed(4) : item.cost_usd.toFixed(2)}`
      : null;
  const durationStr =
    item.duration_ms != null ? `${(item.duration_ms / 1000).toFixed(1)}s` : null;

  return (
    <li className="flex items-start gap-3 py-3 px-4">
      <span
        className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border shrink-0 mt-0.5 ${pillClass}`}
      >
        {pillText}
      </span>
      <span
        className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border shrink-0 mt-0.5 ${srcColor}`}
      >
        {srcLabel}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm truncate">
          {isCompanion ? (
            <span>{item.label}</span>
          ) : item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-corp-accent"
            >
              {item.url}
            </a>
          ) : (
            <span className="text-corp-muted">{item.label}</span>
          )}
        </div>
        <div className="text-[11px] text-corp-muted mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
          {item.attempts != null ? (
            <span>
              {item.attempts} attempt{item.attempts === 1 ? "" : "s"}
            </span>
          ) : null}
          {item.started_at ? (
            <span>
              started {new Date(item.started_at).toLocaleTimeString()}
            </span>
          ) : null}
          {item.updated_at && item.updated_at !== item.started_at ? (
            <span>
              last event {new Date(item.updated_at).toLocaleTimeString()}
            </span>
          ) : null}
          {item.last_tool ? <span>tool: {item.last_tool}</span> : null}
          {durationStr ? <span>{durationStr}</span> : null}
          {costStr ? <span>{costStr}</span> : null}
          {item.num_turns != null ? <span>{item.num_turns} turns</span> : null}
        </div>
        {item.last_text && item.status !== "done" && item.status !== "error" ? (
          <div className="text-xs text-corp-text/80 mt-1 italic truncate">
            {item.last_text}
          </div>
        ) : null}
        {waiting && item.resume_after ? (
          <div className="text-xs text-corp-accent2 mt-1">
            Resumes {new Date(item.resume_after).toLocaleString()}{" "}
            {resumeInPretty ? `(in ${resumeInPretty})` : ""}
            {item.error ? ` · ${item.error}` : ""}
          </div>
        ) : item.status === "error" && item.error ? (
          <div className="text-xs text-corp-danger mt-1 whitespace-pre-wrap">
            {item.error}
          </div>
        ) : null}
        {item.tracked_job_id ? (
          <div className="text-xs mt-1">
            <Link
              href={`/jobs/${item.tracked_job_id}`}
              className="text-corp-accent hover:underline"
            >
              → Open job #{item.tracked_job_id}
            </Link>
          </div>
        ) : null}
      </div>
      <div className="flex gap-1 shrink-0">
        {item.kind === "fetch" &&
        item.status === "error" &&
        item.fetch_queue_id != null ? (
          <button
            className="jsp-btn-ghost text-xs"
            onClick={onRetry}
          >
            Retry
          </button>
        ) : null}
        {item.kind === "fetch" && item.fetch_queue_id != null ? (
          <button
            className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
            onClick={onRemove}
            title="Remove from queue"
          >
            ×
          </button>
        ) : null}
      </div>
    </li>
  );
}

// ---------- Live stream panel ----------------------------------------------

type StreamEvent = {
  kind:
    | "subscribed"
    | "start"
    | "system"
    | "text"
    | "tool_use"
    | "result"
    | "done"
    | "error";
  source?: string;             // "fetch" / "jd_analyze" / "jd_analyze_batch" / ...
  item_id?: number | string;
  label?: string;              // human-readable task description
  url?: string;
  text?: string;
  tool?: string;
  input?: Record<string, unknown>;
  cost_usd?: number | null;
  duration_ms?: number | null;
  num_turns?: number | null;
  created_tracked_job_id?: number | null;
  t?: string;
};

const SOURCE_LABEL: Record<string, string> = {
  fetch: "FETCH",
  score: "SCORE",
  jd_analyze: "SCORE",
  jd_analyze_batch: "SCORE",
  companion: "CHAT",
  tailor_resume: "RESUME",
  tailor_cover_letter: "COVER",
  tailor_outreach_email: "EMAIL",
  tailor_thank_you: "EMAIL",
  tailor_followup: "EMAIL",
  tailor_other: "DOC",
  tailor_portfolio: "DOC",
  tailor_reference: "DOC",
  humanize: "HUMANIZE",
  selection_rewrite: "EDIT",
  selection_answer: "EDIT",
  selection_new_document: "EDIT",
  interview_prep: "INTERVIEW",
  interview_retro: "RETRO",
  strategy: "STRATEGY",
  org_research: "RESEARCH",
  autofill: "AUTOFILL",
  resume_ingest: "INGEST",
};
const SOURCE_COLOR: Record<string, string> = {
  fetch: "bg-sky-500/25 text-sky-300 border-sky-500/40",
  jd_analyze: "bg-corp-accent2/25 text-corp-accent2 border-corp-accent2/40",
  jd_analyze_batch: "bg-corp-accent2/25 text-corp-accent2 border-corp-accent2/40",
  companion: "bg-corp-accent/25 text-corp-accent border-corp-accent/40",
  tailor_resume: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  tailor_cover_letter: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  tailor_outreach_email: "bg-teal-500/25 text-teal-300 border-teal-500/40",
  tailor_thank_you: "bg-teal-500/25 text-teal-300 border-teal-500/40",
  tailor_followup: "bg-teal-500/25 text-teal-300 border-teal-500/40",
  tailor_other: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  tailor_portfolio: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  tailor_reference: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  humanize: "bg-indigo-500/25 text-indigo-300 border-indigo-500/40",
  selection_rewrite: "bg-violet-500/25 text-violet-300 border-violet-500/40",
  selection_answer: "bg-violet-500/25 text-violet-300 border-violet-500/40",
  selection_new_document: "bg-violet-500/25 text-violet-300 border-violet-500/40",
  interview_prep: "bg-rose-500/25 text-rose-300 border-rose-500/40",
  interview_retro: "bg-rose-500/25 text-rose-300 border-rose-500/40",
  strategy: "bg-amber-500/25 text-amber-300 border-amber-500/40",
  org_research: "bg-cyan-500/25 text-cyan-300 border-cyan-500/40",
  autofill: "bg-fuchsia-500/25 text-fuchsia-300 border-fuchsia-500/40",
  resume_ingest: "bg-lime-500/25 text-lime-300 border-lime-500/40",
};

function LiveStreamPanel() {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      esRef.current?.close();
      esRef.current = null;
      setConnected(false);
      return;
    }
    const es = new EventSource(apiUrl("/api/v1/jobs/queue/stream"), {
      withCredentials: true,
    });
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as StreamEvent;
        setEvents((prev) => {
          const next = [...prev, ev];
          // Cap to last 500 so the DOM doesn't balloon.
          return next.length > 500 ? next.slice(next.length - 500) : next;
        });
      } catch {
        /* ignore */
      }
    };
    return () => {
      es.close();
      esRef.current = null;
    };
  }, [open]);

  // Auto-scroll to the bottom unless the user paused.
  useEffect(() => {
    if (paused) return;
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [events.length, paused]);

  return (
    <section className="jsp-card mb-3">
      <header
        className="flex items-center justify-between px-3 py-2 cursor-pointer select-none"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center gap-2">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Live stream
          </h3>
          {open ? (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded border ${
                connected
                  ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                  : "bg-corp-surface2 text-corp-muted border-corp-border"
              }`}
            >
              {connected ? "● connected" : "○ reconnecting"}
            </span>
          ) : (
            <span className="text-[11px] text-corp-muted">
              Watch the Companion narrate what it&apos;s doing as it processes queue items.
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {open ? (
            <>
              <button
                type="button"
                className="jsp-btn-ghost text-xs"
                onClick={(e) => {
                  e.stopPropagation();
                  setPaused((v) => !v);
                }}
              >
                {paused ? "Resume auto-scroll" : "Pause auto-scroll"}
              </button>
              <button
                type="button"
                className="jsp-btn-ghost text-xs"
                onClick={(e) => {
                  e.stopPropagation();
                  setEvents([]);
                }}
              >
                Clear
              </button>
            </>
          ) : null}
          <button type="button" className="jsp-btn-ghost text-xs">
            {open ? "Hide" : "Show"}
          </button>
        </div>
      </header>
      {open ? (
        <div
          ref={logRef}
          className="border-t border-corp-border bg-corp-bg font-mono text-[11px] leading-relaxed p-3 max-h-80 overflow-auto whitespace-pre-wrap"
        >
          {events.length === 0 ? (
            <div className="text-corp-muted italic">
              Waiting for the next item to run… (enqueue a URL or wait for a
              queued item to start)
            </div>
          ) : (
            events.map((ev, i) => <StreamLine key={i} ev={ev} />)
          )}
        </div>
      ) : null}
    </section>
  );
}

function StreamLine({ ev }: { ev: StreamEvent }) {
  const ts = ev.t ? new Date(ev.t).toLocaleTimeString() : "";
  const srcLabel = ev.source ? SOURCE_LABEL[ev.source] ?? ev.source.toUpperCase() : null;
  const srcColor = ev.source ? SOURCE_COLOR[ev.source] ?? "bg-corp-surface2 text-corp-muted border-corp-border" : "";

  const header = (
    <span className="inline-flex items-center gap-1 mr-1">
      <span className="text-corp-muted">[{ts}]</span>
      {srcLabel ? (
        <span className={`px-1 rounded border text-[10px] ${srcColor}`}>{srcLabel}</span>
      ) : null}
      {ev.item_id ? (
        <span className="text-corp-muted">{String(ev.item_id)}</span>
      ) : null}
    </span>
  );

  if (ev.kind === "start") {
    return (
      <div className="text-corp-accent">
        {header}▶ start · {ev.label ?? ev.url}
      </div>
    );
  }
  if (ev.kind === "system") {
    return (
      <div className="text-corp-muted">
        {header}· {ev.text}
      </div>
    );
  }
  if (ev.kind === "subscribed") {
    return (
      <div className="text-corp-muted italic">
        [{ts}] — stream connected
      </div>
    );
  }
  if (ev.kind === "text") {
    return (
      <div className="text-corp-text">
        {header}{ev.text}
      </div>
    );
  }
  if (ev.kind === "tool_use") {
    const inp =
      ev.input && Object.keys(ev.input).length
        ? " " + JSON.stringify(ev.input)
        : "";
    return (
      <div className="text-sky-300">
        {header}● {ev.tool}
        {inp}
      </div>
    );
  }
  if (ev.kind === "result") {
    const bits: string[] = [];
    if (ev.num_turns) bits.push(`${ev.num_turns} turn${ev.num_turns === 1 ? "" : "s"}`);
    if (ev.duration_ms)
      bits.push(
        ev.duration_ms >= 1000 ? `${(ev.duration_ms / 1000).toFixed(1)}s` : `${ev.duration_ms}ms`,
      );
    if (ev.cost_usd && ev.cost_usd > 0) bits.push(`$${ev.cost_usd.toFixed(3)}`);
    return (
      <div className="text-corp-muted italic">
        {header}✓ result · {bits.join(" · ") || "ok"}
      </div>
    );
  }
  if (ev.kind === "done") {
    return (
      <div className="text-emerald-300">
        {header}✓ done
        {ev.created_tracked_job_id ? ` — tracked job #${ev.created_tracked_job_id}` : ""}
      </div>
    );
  }
  if (ev.kind === "error") {
    return (
      <div className="text-corp-danger">
        {header}✗ {ev.text}
      </div>
    );
  }
  return (
    <div className="text-corp-muted">
      {header}{JSON.stringify(ev)}
    </div>
  );
}
