"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";
import type { UserOut } from "@/lib/types";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<UserOut>("/api/v1/auth/me")
      .then((u) => {
        setUser(u);
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

  if (loading) {
    return (
      <PageShell title="Dashboard">
        <p className="text-corp-muted">Loading your corporate record...</p>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Dashboard"
      subtitle={`Welcome back, ${user?.display_name ?? "valued applicant"}. Today promises opportunity, probably.`}
    >
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="jsp-card p-5">
          <div className="text-xs text-corp-muted uppercase tracking-wider">Active Applications</div>
          <div className="text-3xl font-semibold text-corp-accent mt-2">—</div>
          <div className="text-xs text-corp-muted mt-1">No jobs tracked yet.</div>
        </div>
        <div className="jsp-card p-5">
          <div className="text-xs text-corp-muted uppercase tracking-wider">Response Rate</div>
          <div className="text-3xl font-semibold text-corp-accent mt-2">—</div>
          <div className="text-xs text-corp-muted mt-1">Records accrue with use.</div>
        </div>
        <div className="jsp-card p-5">
          <div className="text-xs text-corp-muted uppercase tracking-wider">Upcoming Interviews</div>
          <div className="text-3xl font-semibold text-corp-accent mt-2">—</div>
          <div className="text-xs text-corp-muted mt-1">Anticipate engagement.</div>
        </div>
      </section>

      <section className="jsp-card p-5">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
          Quick Actions
        </h2>
        <div className="flex flex-wrap gap-2">
          <a className="jsp-btn-ghost" href="/jobs">Track a new job</a>
          <a className="jsp-btn-ghost" href="/history">Update history</a>
          <a className="jsp-btn-ghost" href="/companion">Chat with Companion</a>
          <a className="jsp-btn-ghost" href="/studio">Open Document Studio</a>
        </div>
      </section>

      <section className="jsp-card p-5 mt-4">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
          Metrics
        </h2>
        <p className="text-sm text-corp-muted">
          Charts will populate once you have tracked jobs and historical events. The dashboard is
          designed to surface application outcomes, response rates, interview rounds cleared,
          skills distribution, and timeline histograms.
        </p>
      </section>
    </PageShell>
  );
}
