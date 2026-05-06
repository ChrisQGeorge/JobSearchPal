"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

type Settings = {
  enabled: boolean;
  daily_cap: number;
  min_fit_score: number | null;
  only_known_ats: boolean;
  pause_start_hour: number | null;
  pause_end_hour: number | null;
  last_run_at: string | null;
};

type PreviewJob = {
  tracked_job_id: number;
  title: string;
  organization: string | null;
  fit_score: number | null;
  source_url: string | null;
  ats: string | null;
};

type Preview = {
  settings: Settings;
  used_today: number;
  remaining_today: number;
  candidates: PreviewJob[];
};

const DEFAULT_SETTINGS: Settings = {
  enabled: false,
  daily_cap: 5,
  min_fit_score: null,
  only_known_ats: false,
  pause_start_hour: null,
  pause_end_hour: null,
  last_run_at: null,
};

export default function AutoApplyPage() {
  const [s, setS] = useState<Settings>(DEFAULT_SETTINGS);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const p = await api.get<Preview>("/api/v1/auto-apply/preview");
      setPreview(p);
      setS(p.settings);
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function save() {
    setSaving(true);
    setMsg(null);
    setErr(null);
    try {
      await api.put<Settings>("/api/v1/auto-apply/settings", s);
      setMsg("Saved.");
      await refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function runNow() {
    setRunning(true);
    setMsg(null);
    setErr(null);
    try {
      const res = await api.post<{ spawned: number }>(
        "/api/v1/auto-apply/run-now",
      );
      setMsg(
        res.spawned > 0
          ? `Spawned ${res.spawned} application run${res.spawned === 1 ? "" : "s"}.`
          : "Nothing to do — no eligible candidates or daily cap reached.",
      );
      await refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message || `HTTP ${e.status}` : "Run failed.");
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return (
      <PageShell title="Auto-Apply">
        <p className="text-corp-muted">Loading auto-apply policy...</p>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Auto-Apply"
      subtitle="Let the Companion submit applications for your interested jobs on autopilot. Subject to a daily cap and fit-score gate. You will still be paged for novel questions."
    >
      <section className="jsp-card p-5 mb-4">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
          Policy
        </h2>

        <label className="flex items-center gap-2 mb-3">
          <input
            type="checkbox"
            checked={s.enabled}
            onChange={(e) => setS({ ...s, enabled: e.target.checked })}
          />
          <span>Enable auto-apply</span>
          <span className="text-xs text-corp-muted">
            (poller wakes every 5 min)
          </span>
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Daily cap" hint="Max submissions per UTC day. 0 disables.">
            <input
              type="number"
              min={0}
              max={100}
              value={s.daily_cap}
              onChange={(e) =>
                setS({ ...s, daily_cap: parseInt(e.target.value || "0", 10) })
              }
              className="jsp-input w-24"
            />
          </Field>

          <Field
            label="Min fit-score"
            hint="0-100 from JD analyzer. Blank = no minimum."
          >
            <input
              type="number"
              min={0}
              max={100}
              value={s.min_fit_score ?? ""}
              onChange={(e) =>
                setS({
                  ...s,
                  min_fit_score:
                    e.target.value === "" ? null : parseInt(e.target.value, 10),
                })
              }
              className="jsp-input w-24"
            />
          </Field>

          <Field
            label="Pause window (start hour, UTC)"
            hint="Skip ticks during these hours. 0-23. Blank = no pause."
          >
            <input
              type="number"
              min={0}
              max={23}
              value={s.pause_start_hour ?? ""}
              onChange={(e) =>
                setS({
                  ...s,
                  pause_start_hour:
                    e.target.value === "" ? null : parseInt(e.target.value, 10),
                })
              }
              className="jsp-input w-24"
            />
          </Field>

          <Field label="Pause window (end hour, UTC)">
            <input
              type="number"
              min={0}
              max={23}
              value={s.pause_end_hour ?? ""}
              onChange={(e) =>
                setS({
                  ...s,
                  pause_end_hour:
                    e.target.value === "" ? null : parseInt(e.target.value, 10),
                })
              }
              className="jsp-input w-24"
            />
          </Field>
        </div>

        <label className="flex items-center gap-2 mt-3">
          <input
            type="checkbox"
            checked={s.only_known_ats}
            onChange={(e) => setS({ ...s, only_known_ats: e.target.checked })}
          />
          <span>Only auto-apply to known ATS hosts</span>
          <span className="text-xs text-corp-muted">
            (greenhouse / lever / ashby / workable)
          </span>
        </label>

        <div className="mt-4 flex gap-2 flex-wrap">
          <button
            type="button"
            className="jsp-btn"
            onClick={save}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save policy"}
          </button>
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={runNow}
            disabled={running || !s.enabled}
          >
            {running ? "Running…" : "Run one tick now"}
          </button>
          {msg ? <span className="text-xs text-corp-ok self-center">{msg}</span> : null}
          {err ? <span className="text-xs text-corp-danger self-center">{err}</span> : null}
        </div>
      </section>

      {preview ? (
        <section className="jsp-card p-5">
          <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-3">
            Preview — what would the next tick do?
          </h2>
          <div className="text-sm text-corp-muted mb-3">
            Used today: <span className="text-corp-text">{preview.used_today}</span> ·{" "}
            Remaining: <span className="text-corp-text">{preview.remaining_today}</span> ·{" "}
            Last tick:{" "}
            <span className="text-corp-text">
              {preview.settings.last_run_at
                ? new Date(preview.settings.last_run_at).toLocaleString()
                : "never"}
            </span>
          </div>
          {preview.candidates.length === 0 ? (
            <p className="text-sm text-corp-muted">
              No eligible candidates. Mark some jobs{" "}
              <Link href="/jobs" className="text-corp-accent hover:underline">
                Interested
              </Link>{" "}
              and run the JD analyzer to surface fit-scores.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-corp-muted">
                <tr>
                  <th className="py-1">#</th>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Fit</th>
                  <th>ATS</th>
                </tr>
              </thead>
              <tbody>
                {preview.candidates.map((j, i) => (
                  <tr key={j.tracked_job_id} className="border-t border-corp-border">
                    <td className="py-1.5">{i + 1}</td>
                    <td>
                      <Link
                        href={`/jobs/${j.tracked_job_id}`}
                        className="text-corp-accent hover:underline"
                      >
                        {j.title}
                      </Link>
                    </td>
                    <td>{j.organization ?? "—"}</td>
                    <td>{j.fit_score ?? "—"}</td>
                    <td>{j.ats ?? "generic"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}
    </PageShell>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-corp-muted mb-1">
        {label}
      </div>
      {children}
      {hint ? <div className="text-xs text-corp-muted mt-1">{hint}</div> : null}
    </div>
  );
}
