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

const STATE_STYLES: Record<JobFetchQueueState, string> = {
  queued: "bg-corp-surface2 text-corp-muted border-corp-border",
  processing: "bg-sky-500/25 text-sky-300 border-sky-500/40 animate-pulse",
  done: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  error: "bg-corp-danger/20 text-corp-danger border-corp-danger/40",
};

const WAITING_STYLE =
  "bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40";

function isWaiting(it: JobFetchQueueItem): boolean {
  return !!it.resume_after && new Date(it.resume_after) > new Date();
}

export default function QueuePage() {
  const [items, setItems] = useState<JobFetchQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("active");
  const [url, setUrl] = useState("");
  const [desiredStatus, setDesiredStatus] = useState<JobStatus | "">("");
  const [desiredApplied, setDesiredApplied] = useState("");
  const [desiredPosted, setDesiredPosted] = useState("");
  const [adding, setAdding] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function refresh() {
    try {
      const data = await api.get<JobFetchQueueItem[]>("/api/v1/jobs/queue");
      // newest-first so the most recent activity is at the top
      data.sort((a, b) => b.id - a.id);
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

  // Poll on a schedule: 3s when anything is actively moving, else 15s.
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    const active = items.some(
      (i) =>
        (i.state === "queued" || i.state === "processing") && !isWaiting(i),
    );
    const ms = active ? 3000 : 15000;
    pollRef.current = setInterval(refresh, ms);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.map((i) => i.state + (i.resume_after ?? "")).join(",")]);

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

  async function retry(id: number) {
    await api.post(`/api/v1/jobs/queue/${id}/retry`);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Remove this queue item?")) return;
    await api.delete(`/api/v1/jobs/queue/${id}`);
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
      else if (it.state === "processing") {
        processing++;
        active++;
      } else if (it.state === "queued") active++;
      else if (it.state === "done") done++;
      else if (it.state === "error") errored++;
    }
    return { active, waiting, done, errored, processing, total: items.length };
  }, [items]);

  const visible = useMemo(() => {
    switch (filter) {
      case "all":
        return items;
      case "active":
        return items.filter(
          (i) =>
            (i.state === "queued" || i.state === "processing") && !isWaiting(i),
        );
      case "waiting":
        return items.filter(isWaiting);
      case "done":
        return items.filter((i) => i.state === "done");
      case "error":
        return items.filter((i) => i.state === "error");
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
      title="Fetch Queue"
      subtitle="URLs waiting for the Companion to turn into TrackedJobs. Rate-limited items back off and resume automatically."
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
              onRetry={() => retry(it.id)}
              onRemove={() => remove(it.id)}
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
  item: JobFetchQueueItem;
  onRetry: () => void;
  onRemove: () => void;
}) {
  const waiting = isWaiting(item);
  const pillClass = waiting ? WAITING_STYLE : STATE_STYLES[item.state];
  const pillText = waiting ? "waiting" : item.state;

  const resumeIn = item.resume_after
    ? Math.max(0, Math.floor((new Date(item.resume_after).getTime() - Date.now()) / 60000))
    : null;

  return (
    <li className="flex items-start gap-3 py-3 px-4">
      <span
        className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border shrink-0 mt-0.5 ${pillClass}`}
      >
        {pillText}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm truncate">
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-corp-accent"
          >
            {item.url}
          </a>
        </div>
        <div className="text-[11px] text-corp-muted mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
          {item.desired_status ? <span>→ {item.desired_status}</span> : null}
          {item.desired_priority ? <span>pri: {item.desired_priority}</span> : null}
          {item.desired_date_applied ? (
            <span>applied {item.desired_date_applied}</span>
          ) : null}
          {item.desired_date_posted ? (
            <span>posted {item.desired_date_posted}</span>
          ) : null}
          {item.desired_date_closed ? (
            <span>closed {item.desired_date_closed}</span>
          ) : null}
          <span>
            {item.attempts} attempt{item.attempts === 1 ? "" : "s"}
          </span>
          {item.last_attempt_at ? (
            <span>
              last tried {new Date(item.last_attempt_at).toLocaleString()}
            </span>
          ) : null}
        </div>
        {waiting && item.resume_after ? (
          <div className="text-xs text-corp-accent2 mt-1">
            Resumes {new Date(item.resume_after).toLocaleString()}{" "}
            {resumeIn !== null ? `(≈${resumeIn} min)` : ""}
            {item.error_message ? ` · ${item.error_message}` : ""}
          </div>
        ) : item.error_message ? (
          <div className="text-xs text-corp-danger mt-1">{item.error_message}</div>
        ) : null}
        {item.created_tracked_job_id ? (
          <div className="text-xs mt-1">
            <Link
              href={`/jobs/${item.created_tracked_job_id}`}
              className="text-corp-accent hover:underline"
            >
              → Open job #{item.created_tracked_job_id}
            </Link>
          </div>
        ) : null}
      </div>
      <div className="flex gap-1 shrink-0">
        {item.state === "error" ? (
          <button className="jsp-btn-ghost text-xs" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        <button
          className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
          onClick={onRemove}
          title="Remove from queue"
        >
          ×
        </button>
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
  item_id?: number;
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
  const itemTag = ev.item_id ? `#${ev.item_id}` : "";
  const prefix = `[${ts}${itemTag ? ` ${itemTag}` : ""}]`;

  if (ev.kind === "start") {
    return (
      <div className="text-corp-accent">
        {prefix} ▶ start · {ev.url}
      </div>
    );
  }
  if (ev.kind === "system") {
    return (
      <div className="text-corp-muted">
        {prefix} · {ev.text}
      </div>
    );
  }
  if (ev.kind === "subscribed") {
    return (
      <div className="text-corp-muted italic">
        {prefix} — stream connected
      </div>
    );
  }
  if (ev.kind === "text") {
    return (
      <div className="text-corp-text">
        {prefix} {ev.text}
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
        {prefix} ● {ev.tool}
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
        {prefix} ✓ result · {bits.join(" · ") || "ok"}
      </div>
    );
  }
  if (ev.kind === "done") {
    return (
      <div className="text-emerald-300">
        {prefix} ✓ done — tracked job #{ev.created_tracked_job_id}
      </div>
    );
  }
  if (ev.kind === "error") {
    return (
      <div className="text-corp-danger">
        {prefix} ✗ {ev.text}
      </div>
    );
  }
  return (
    <div className="text-corp-muted">
      {prefix} {JSON.stringify(ev)}
    </div>
  );
}
