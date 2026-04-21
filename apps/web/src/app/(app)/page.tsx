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
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
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
  tone?: "good";
}) {
  const toneClass = tone === "good" ? "text-emerald-300" : "text-corp-accent";
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
