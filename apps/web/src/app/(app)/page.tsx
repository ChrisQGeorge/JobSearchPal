"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError } from "@/lib/api";
import {
  JOB_STATUSES,
  type JobStatus,
  type TrackedJobSummary,
  type UserOut,
} from "@/lib/types";

const ACTIVE_STATUSES: JobStatus[] = [
  "applied",
  "responded",
  "screening",
  "interviewing",
  "assessment",
  "offer",
];

const POST_APPLY_STATUSES: JobStatus[] = [
  "responded",
  "screening",
  "interviewing",
  "assessment",
  "offer",
  "won",
];

// Standard application pipeline — lanes in the funnel, in order.
const FUNNEL: JobStatus[] = [
  "watching",
  "interested",
  "applied",
  "responded",
  "screening",
  "interviewing",
  "assessment",
  "offer",
  "won",
];

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [jobs, setJobs] = useState<TrackedJobSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<UserOut>("/api/v1/auth/me"),
      api.get<TrackedJobSummary[]>("/api/v1/jobs"),
    ])
      .then(([u, js]) => {
        setUser(u);
        setJobs(js);
        setLoading(false);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        } else {
          setLoading(false);
        }
      });
  }, [router]);

  const metrics = useMemo(() => computeMetrics(jobs), [jobs]);

  if (loading) {
    return (
      <PageShell title="Dashboard">
        <p className="text-corp-muted">Loading your corporate record...</p>
      </PageShell>
    );
  }

  const hasAnyJobs = jobs.length > 0;

  return (
    <PageShell
      title="Dashboard"
      subtitle={`Welcome back, ${user?.display_name ?? "valued applicant"}. Today promises opportunity, probably.`}
    >
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
        <Kpi
          label="To review"
          value={metrics.statusCounts.get("to_review") ?? 0}
          sub={
            (metrics.statusCounts.get("to_review") ?? 0) > 0
              ? "Click to triage →"
              : "Queue is clear"
          }
          href="/jobs/review"
          tone={
            (metrics.statusCounts.get("to_review") ?? 0) > 0 ? "warn" : undefined
          }
        />
        <Kpi
          label="Ready to apply"
          value={metrics.statusCounts.get("interested") ?? 0}
          sub={
            (metrics.statusCounts.get("interested") ?? 0) > 0
              ? "Click to start applying →"
              : "Nothing queued"
          }
          href="/jobs/apply"
        />
        <Kpi
          label="Active applications"
          value={metrics.activeCount}
          sub={
            metrics.activeCount > 0
              ? `of ${jobs.length} tracked`
              : "Add your first job →"
          }
          href="/jobs"
        />
        <Kpi
          label="Response rate"
          value={metrics.responseRate !== null ? `${metrics.responseRate}%` : "—"}
          sub={
            metrics.responseRate !== null
              ? `${metrics.postApplyCount} / ${metrics.appliedCount} responded`
              : "Needs applications to compute"
          }
        />
        <Kpi
          label="Offers won"
          value={metrics.wonCount}
          sub={metrics.wonCount > 0 ? "Congrats." : "Patience is an asset."}
          tone={metrics.wonCount > 0 ? "good" : undefined}
        />
        <Kpi
          label="Applied this week"
          value={metrics.appliedThisWeek}
          sub={
            metrics.appliedThisWeek > 0
              ? `${metrics.appliedLast30Days} in last 30 days`
              : "Pace is a choice."
          }
        />
      </section>

      {hasAnyJobs ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <section className="jsp-card p-5">
            <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
              Status distribution
            </h2>
            <StatusBarChart counts={metrics.statusCounts} />
          </section>

          <section className="jsp-card p-5">
            <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
              Pipeline funnel
            </h2>
            <FunnelChart counts={metrics.funnelCounts} />
          </section>

          <section className="jsp-card p-5 md:col-span-2">
            <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
              Activity — last 30 days
            </h2>
            <ActivitySparkline series={metrics.activitySeries} />
          </section>

          <section className="jsp-card p-5 md:col-span-2">
            <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
              Application-to-response funnel by source
            </h2>
            <SourceFunnelPanel />
          </section>
        </div>
      ) : (
        <section className="jsp-card p-5">
          <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
            Metrics
          </h2>
          <p className="text-sm text-corp-muted">
            Charts will populate once you have tracked jobs. Open the{" "}
            <Link href="/jobs" className="text-corp-accent hover:underline">
              Job Tracker
            </Link>{" "}
            and add your first application.
          </p>
        </section>
      )}

      <StrategyPanel />

      <section className="jsp-card p-5 mt-4">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
          Quick actions
        </h2>
        <div className="flex flex-wrap gap-2">
          <Link className="jsp-btn-ghost" href="/jobs">
            Track a new job
          </Link>
          <Link className="jsp-btn-ghost" href="/history">
            Update history
          </Link>
          <Link className="jsp-btn-ghost" href="/companion">
            Chat with Companion
          </Link>
          <Link className="jsp-btn-ghost" href="/studio">
            Open Document Studio
          </Link>
          <Link className="jsp-btn-ghost" href="/samples">
            Writing samples
          </Link>
        </div>
      </section>
    </PageShell>
  );
}

// ---------- metrics ---------------------------------------------------------

type Metrics = {
  activeCount: number;
  appliedCount: number;
  postApplyCount: number;
  responseRate: number | null;
  wonCount: number;
  appliedThisWeek: number;
  appliedLast30Days: number;
  statusCounts: Map<JobStatus, number>;
  funnelCounts: Array<{ status: JobStatus; count: number }>;
  activitySeries: Array<{ date: string; count: number }>;
};

function computeMetrics(jobs: TrackedJobSummary[]): Metrics {
  const statusCounts = new Map<JobStatus, number>();
  for (const s of JOB_STATUSES) statusCounts.set(s, 0);
  for (const j of jobs) {
    statusCounts.set(j.status, (statusCounts.get(j.status) ?? 0) + 1);
  }

  const activeCount = ACTIVE_STATUSES.reduce(
    (sum, s) => sum + (statusCounts.get(s) ?? 0),
    0,
  );
  const appliedCount = jobs.filter((j) => j.date_applied).length;
  const postApplyCount = jobs.filter(
    (j) => j.date_applied && POST_APPLY_STATUSES.includes(j.status),
  ).length;
  const responseRate =
    appliedCount > 0 ? Math.round((postApplyCount / appliedCount) * 100) : null;
  const wonCount = statusCounts.get("won") ?? 0;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 7);
  const thirtyAgo = new Date(today);
  thirtyAgo.setDate(thirtyAgo.getDate() - 30);

  const appliedThisWeek = jobs.filter(
    (j) => j.date_applied && new Date(j.date_applied) >= weekAgo,
  ).length;
  const appliedLast30Days = jobs.filter(
    (j) => j.date_applied && new Date(j.date_applied) >= thirtyAgo,
  ).length;

  // Activity series: updated_at counts per day for last 30 days.
  const dayBuckets = new Map<string, number>();
  for (let i = 0; i < 30; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() - (29 - i));
    dayBuckets.set(d.toISOString().slice(0, 10), 0);
  }
  for (const j of jobs) {
    const key = new Date(j.updated_at).toISOString().slice(0, 10);
    if (dayBuckets.has(key)) {
      dayBuckets.set(key, (dayBuckets.get(key) ?? 0) + 1);
    }
  }
  const activitySeries = Array.from(dayBuckets.entries()).map(([date, count]) => ({
    date,
    count,
  }));

  const funnelCounts = FUNNEL.map((s) => ({
    status: s,
    count: statusCounts.get(s) ?? 0,
  }));

  return {
    activeCount,
    appliedCount,
    postApplyCount,
    responseRate,
    wonCount,
    appliedThisWeek,
    appliedLast30Days,
    statusCounts,
    funnelCounts,
    activitySeries,
  };
}

// ---------- primitives ------------------------------------------------------

function Kpi({
  label,
  value,
  sub,
  href,
  tone,
}: {
  label: string;
  value: number | string;
  sub?: string;
  href?: string;
  tone?: "good" | "warn";
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-300"
      : tone === "warn"
        ? "text-corp-accent2"
        : "text-corp-accent";
  const body = (
    <div className="jsp-card p-5 h-full">
      <div className="text-xs text-corp-muted uppercase tracking-wider">{label}</div>
      <div className={`text-3xl font-semibold ${toneClass} mt-2`}>{value}</div>
      {sub ? <div className="text-xs text-corp-muted mt-1">{sub}</div> : null}
    </div>
  );
  if (href) {
    return (
      <Link href={href} className="block hover:opacity-90 transition-opacity">
        {body}
      </Link>
    );
  }
  return body;
}

function StatusBarChart({ counts }: { counts: Map<JobStatus, number> }) {
  const entries = JOB_STATUSES.map((s) => [s, counts.get(s) ?? 0] as const).filter(
    ([, n]) => n > 0,
  );
  if (entries.length === 0) {
    return <p className="text-sm text-corp-muted">No data yet.</p>;
  }
  const max = Math.max(...entries.map(([, n]) => n), 1);
  return (
    <div className="space-y-1.5">
      {entries.map(([s, n]) => {
        const pct = Math.max(4, Math.round((n / max) * 100));
        return (
          <div key={s} className="flex items-center gap-2">
            <div className="w-28 shrink-0">
              <StatusBadge status={s} />
            </div>
            <div className="flex-1 bg-corp-surface2 rounded h-5 overflow-hidden border border-corp-border">
              <div
                className="h-full bg-corp-accent/60"
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="text-sm w-8 text-right tabular-nums">{n}</div>
          </div>
        );
      })}
    </div>
  );
}

function FunnelChart({
  counts,
}: {
  counts: Array<{ status: JobStatus; count: number }>;
}) {
  const max = Math.max(...counts.map((c) => c.count), 1);
  const nonZero = counts.filter((c) => c.count > 0);
  if (nonZero.length === 0) {
    return (
      <p className="text-sm text-corp-muted">
        Move jobs through statuses and the funnel populates automatically.
      </p>
    );
  }
  return (
    <div className="space-y-1">
      {counts.map(({ status, count }) => {
        const pct = count === 0 ? 2 : Math.max(6, Math.round((count / max) * 100));
        const muted = count === 0;
        return (
          <div
            key={status}
            className={`flex items-center gap-2 ${muted ? "opacity-40" : ""}`}
          >
            <div className="w-28 shrink-0">
              <StatusBadge status={status} />
            </div>
            <div className="flex-1 bg-corp-surface2 rounded h-6 overflow-hidden border border-corp-border relative">
              <div
                className="h-full bg-corp-accent/40 border-r border-corp-accent/70"
                style={{ width: `${pct}%` }}
              />
              <span className="absolute inset-0 flex items-center px-2 text-xs tabular-nums">
                {count}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ActivitySparkline({
  series,
}: {
  series: Array<{ date: string; count: number }>;
}) {
  const total = series.reduce((s, p) => s + p.count, 0);
  if (total === 0) {
    return (
      <p className="text-sm text-corp-muted">
        No updates in the last 30 days yet.
      </p>
    );
  }
  const max = Math.max(...series.map((p) => p.count), 1);
  const w = 800;
  const h = 120;
  const padY = 8;
  const barW = w / series.length;
  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full"
        preserveAspectRatio="xMidYMid meet"
      >
        {series.map((p, i) => {
          const barH = (p.count / max) * (h - padY * 2);
          const x = i * barW + 1;
          const y = h - padY - barH;
          return (
            <g key={p.date}>
              <rect
                x={x}
                y={y}
                width={Math.max(1, barW - 2)}
                height={Math.max(1, barH)}
                className="fill-corp-accent/70"
              />
              <title>
                {p.date}: {p.count} update{p.count === 1 ? "" : "s"}
              </title>
            </g>
          );
        })}
        <line
          x1={0}
          y1={h - padY}
          x2={w}
          y2={h - padY}
          className="stroke-corp-border"
          strokeWidth={0.5}
        />
      </svg>
      <div className="flex justify-between text-[10px] text-corp-muted mt-1">
        <span>{series[0]?.date}</span>
        <span>{total} updates</span>
        <span>{series[series.length - 1]?.date}</span>
      </div>
    </div>
  );
}

type StrategyResult = {
  headline: string;
  working_well: string[];
  struggling: string[];
  next_actions: string[];
  risks: string[];
  warning?: string | null;
};

/** Application-to-response funnel grouped by source_platform — answers
 * "where am I getting traction?" Shows a tiny per-source bar chart with
 * absolute counts and rate-from-applied (so a source with 80 applies and
 * 1 onsite reads weaker than a source with 4 applies and 2 onsites). */
type FunnelStage = { stage: string; count: number; rate_from_applied: number | null };
type FunnelRow = { source: string; total: number; stages: FunnelStage[] };

function SourceFunnelPanel() {
  const [rows, setRows] = useState<FunnelRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<FunnelRow[]>("/api/v1/metrics/funnel-by-source")
      .then((r) => setRows(r))
      .catch((e) =>
        setErr(
          e instanceof ApiError
            ? `Funnel load failed (HTTP ${e.status}).`
            : "Funnel load failed.",
        ),
      );
  }, []);

  if (err) {
    return <p className="text-sm text-corp-danger">{err}</p>;
  }
  if (rows === null) {
    return <p className="text-sm text-corp-muted">Loading…</p>;
  }
  // Filter out sources that never reached `applied` — they clutter the
  // table without adding signal (those are jobs you tracked but didn't
  // actually apply to).
  const nonZero = rows.filter((r) => r.stages[0]?.count > 0);
  if (nonZero.length === 0) {
    return (
      <p className="text-sm text-corp-muted">
        No applications yet — funnel populates once you mark a job as applied.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-corp-muted border-b border-corp-border">
            <th className="py-2 pr-4">Source</th>
            <th className="py-2 px-2 text-right">Tracked</th>
            {nonZero[0].stages.map((s) => (
              <th key={s.stage} className="py-2 px-2 text-right">
                {s.stage.replace(/_/g, " ")}
              </th>
            ))}
            <th className="py-2 pl-2 text-right">→ offer</th>
          </tr>
        </thead>
        <tbody>
          {nonZero.map((r) => {
            const offerRate =
              r.stages.find((s) => s.stage === "offer")?.rate_from_applied ?? null;
            return (
              <tr key={r.source} className="border-b border-corp-border/50">
                <td className="py-1.5 pr-4 truncate max-w-[180px]" title={r.source}>
                  {r.source}
                </td>
                <td className="py-1.5 px-2 text-right text-corp-muted tabular-nums">
                  {r.total}
                </td>
                {r.stages.map((s) => (
                  <td
                    key={s.stage}
                    className="py-1.5 px-2 text-right tabular-nums"
                    title={
                      s.rate_from_applied !== null
                        ? `${s.rate_from_applied}% of applied`
                        : undefined
                    }
                  >
                    {s.count}
                    {s.rate_from_applied !== null && s.stage !== "applied" ? (
                      <span className="ml-1 text-[10px] text-corp-muted">
                        ({s.rate_from_applied}%)
                      </span>
                    ) : null}
                  </td>
                ))}
                <td
                  className={`py-1.5 pl-2 text-right tabular-nums ${
                    offerRate != null && offerRate >= 10
                      ? "text-emerald-300"
                      : offerRate != null && offerRate > 0
                        ? "text-corp-accent"
                        : "text-corp-muted"
                  }`}
                >
                  {offerRate !== null ? `${offerRate}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-[11px] text-corp-muted mt-2">
        Rate-from-applied per stage in parentheses. Source “(unknown)” means
        the job didn't have a source_platform set — fill that in on the
        tracker for cleaner attribution.
      </p>
    </div>
  );
}


function StrategyPanel() {
  const [result, setResult] = useState<StrategyResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setErr(null);
    try {
      setResult(await api.post<StrategyResult>("/api/v1/metrics/strategy"));
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Strategy failed (HTTP ${e.status}).`
          : "Strategy failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  async function snapshot() {
    setErr(null);
    try {
      await api.post("/api/v1/metrics/snapshot");
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Snapshot failed.");
    }
  }

  return (
    <section className="jsp-card p-5 mt-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm uppercase tracking-wider text-corp-muted">
            Strategy advisor
          </h2>
          <p className="text-xs text-corp-muted mt-1">
            Reads your pipeline snapshot + recent snapshot history and tells you
            where to push, where to stop bleeding time, and what to watch.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="jsp-btn-ghost text-xs"
            onClick={snapshot}
          >
            Save snapshot
          </button>
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={run}
            disabled={running}
          >
            {running ? "Thinking..." : "Advise me"}
          </button>
        </div>
      </div>
      {err ? <div className="text-xs text-corp-danger mt-2">{err}</div> : null}
      {result ? (
        <div className="mt-3 space-y-3">
          {result.warning ? (
            <div className="text-xs text-corp-accent2 bg-corp-accent2/10 border border-corp-accent2/40 p-2 rounded">
              ⚠ {result.warning}
            </div>
          ) : null}
          <p className="text-sm font-medium">{result.headline}</p>
          <div className="grid grid-cols-2 gap-4 text-sm">
            {result.working_well.length ? (
              <StratBullets label="Working well" items={result.working_well} tone="good" />
            ) : null}
            {result.struggling.length ? (
              <StratBullets label="Struggling" items={result.struggling} tone="warn" />
            ) : null}
            {result.next_actions.length ? (
              <StratBullets
                label="Next actions"
                items={result.next_actions}
              />
            ) : null}
            {result.risks.length ? (
              <StratBullets label="Risks" items={result.risks} tone="danger" />
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function StratBullets({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone?: "good" | "warn" | "danger";
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-300"
      : tone === "warn"
        ? "text-corp-accent2"
        : tone === "danger"
          ? "text-corp-danger"
          : "text-corp-muted";
  return (
    <div>
      <div className={`text-[10px] uppercase tracking-wider mb-1 ${toneClass}`}>
        {label}
      </div>
      <ul className="list-disc list-inside space-y-0.5">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}
