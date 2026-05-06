"use client";

// Application-run dashboard (R10.4).
//
// Two columns: list of every run on the left, selected run's detail on
// the right. The detail panel surfaces the step transcript, any pending
// question (with an answer field), and a Cancel button. New runs are
// created from the tracked-job tracker via the "Apply with Companion"
// button — this page just monitors them.

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

type ApplicationRun = {
  id: number;
  tracked_job_id: number;
  tier: string;
  state: string;
  ats_kind: string | null;
  started_at: string | null;
  finished_at: string | null;
  queue_id: number | null;
  cost_usd: number | null;
  error_message: string | null;
  pending_question: string | null;
  created_at: string;
  updated_at: string;
};

type RunStep = {
  id: number;
  ts: string;
  kind: string;
  payload: Record<string, unknown> | null;
  screenshot_url: string | null;
};

type RunDetail = ApplicationRun & {
  steps: RunStep[];
  tracked_job_title: string | null;
};

const STATE_TONE: Record<string, string> = {
  queued: "bg-corp-surface2 text-corp-muted border-corp-border",
  running: "bg-sky-500/25 text-sky-300 border-sky-500/40 animate-pulse",
  awaiting_user: "bg-corp-accent2/25 text-corp-accent2 border-corp-accent2/40",
  submitted: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40",
  failed: "bg-corp-danger/25 text-corp-danger border-corp-danger/40",
  cancelled: "bg-corp-surface2 text-corp-muted border-corp-border line-through",
};

export default function ApplicationsPage() {
  const [runs, setRuns] = useState<ApplicationRun[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [saveToBank, setSaveToBank] = useState(true);
  const [submittingAnswer, setSubmittingAnswer] = useState(false);

  async function refresh() {
    try {
      const rows = await api.get<ApplicationRun[]>("/api/v1/application-runs");
      setRuns(rows);
      setErr(null);
      if (selectedId === null && rows.length > 0) {
        setSelectedId(rows[0].id);
      }
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Load failed (HTTP ${e.status}).`
          : "Load failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id: number) {
    try {
      const d = await api.get<RunDetail>(`/api/v1/application-runs/${id}`);
      setDetail(d);
      setAnswer("");
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Detail load failed (HTTP ${e.status}).`
          : "Detail load failed.",
      );
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedId !== null) loadDetail(selectedId);
  }, [selectedId]);

  // Auto-refresh detail when the selected run is in motion.
  useEffect(() => {
    if (!detail) return;
    if (!["running", "queued", "awaiting_user"].includes(detail.state)) return;
    const t = setInterval(() => {
      if (selectedId !== null) loadDetail(selectedId);
    }, 4_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.state, selectedId]);

  async function submitAnswer() {
    if (!detail) return;
    if (!answer.trim()) return;
    setSubmittingAnswer(true);
    try {
      await api.post(`/api/v1/application-runs/${detail.id}/answer`, {
        answer: answer.trim(),
        save_to_bank: saveToBank,
      });
      setAnswer("");
      await refresh();
      await loadDetail(detail.id);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Answer submit failed (HTTP ${e.status}).`
          : "Answer submit failed.",
      );
    } finally {
      setSubmittingAnswer(false);
    }
  }

  async function cancel() {
    if (!detail) return;
    if (!confirm("Cancel this application run?")) return;
    try {
      await api.post(`/api/v1/application-runs/${detail.id}/cancel`, {});
      await refresh();
      await loadDetail(detail.id);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Cancel failed (HTTP ${e.status}).`
          : "Cancel failed.",
      );
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = {
      queued: 0,
      running: 0,
      awaiting_user: 0,
      submitted: 0,
      failed: 0,
      cancelled: 0,
    };
    for (const r of runs) c[r.state] = (c[r.state] ?? 0) + 1;
    return c;
  }, [runs]);

  return (
    <PageShell
      title="Application Runs"
      subtitle="Companion-driven application attempts — start one from a tracked job, watch progress here, answer pending questions in-line."
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger mb-3">{err}</div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-5 gap-2 mb-3">
        {(
          [
            ["awaiting_user", "Needs you"],
            ["running", "Running"],
            ["queued", "Queued"],
            ["submitted", "Submitted"],
            ["failed", "Failed"],
          ] as const
        ).map(([k, label]) => (
          <div
            key={k}
            className="jsp-card p-3 flex items-center justify-between"
          >
            <span className="text-[11px] uppercase tracking-wider text-corp-muted">
              {label}
            </span>
            <span className="text-2xl font-semibold tabular-nums">
              {counts[k] ?? 0}
            </span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-3">
        <div className="jsp-card p-2 max-h-[70vh] overflow-y-auto">
          {loading ? (
            <p className="text-sm text-corp-muted p-3">Loading…</p>
          ) : runs.length === 0 ? (
            <p className="text-sm text-corp-muted p-3">
              No application runs yet. Start one from a tracked job — open
              <Link href="/jobs" className="text-corp-accent">
                {" /jobs "}
              </Link>
              and click <b>Apply with Companion</b> on a row.
            </p>
          ) : (
            <ul className="divide-y divide-corp-border">
              {runs.map((r) => (
                <li
                  key={r.id}
                  className={`p-2 cursor-pointer ${
                    selectedId === r.id
                      ? "bg-corp-accent/10"
                      : "hover:bg-corp-surface2"
                  }`}
                  onClick={() => setSelectedId(r.id)}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border shrink-0 ${
                        STATE_TONE[r.state] ?? STATE_TONE.queued
                      }`}
                    >
                      {r.state.replace(/_/g, " ")}
                    </span>
                    <span className="text-sm flex-1 truncate">
                      Run #{r.id}
                    </span>
                  </div>
                  <div className="text-[11px] text-corp-muted mt-0.5 truncate">
                    {[
                      r.ats_kind ?? "generic",
                      `tracked-job ${r.tracked_job_id}`,
                      r.cost_usd != null ? `$${Number(r.cost_usd).toFixed(2)}` : null,
                      new Date(r.updated_at).toLocaleString(),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="jsp-card p-3">
          {!detail ? (
            <p className="text-sm text-corp-muted">
              Select a run on the left to see its transcript.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border ${
                      STATE_TONE[detail.state] ?? STATE_TONE.queued
                    }`}
                  >
                    {detail.state.replace(/_/g, " ")}
                  </span>
                  <span className="text-sm ml-2">
                    Run #{detail.id} ·{" "}
                    {detail.tracked_job_title || `tracked-job ${detail.tracked_job_id}`}
                  </span>
                </div>
                <div className="flex gap-2">
                  <Link
                    href="/browser"
                    className="jsp-btn-ghost text-xs"
                    title="Watch the streamed browser"
                  >
                    Watch browser →
                  </Link>
                  <Link
                    href={`/jobs/${detail.tracked_job_id}`}
                    className="jsp-btn-ghost text-xs"
                  >
                    Tracked job →
                  </Link>
                  {!["submitted", "failed", "cancelled"].includes(detail.state) ? (
                    <button
                      type="button"
                      className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                      onClick={cancel}
                    >
                      Cancel
                    </button>
                  ) : null}
                </div>
              </div>

              {detail.error_message ? (
                <div className="text-xs text-corp-danger border-l-2 border-corp-danger pl-2">
                  {detail.error_message}
                </div>
              ) : null}

              {detail.state === "awaiting_user" && detail.pending_question ? (
                <div className="jsp-card p-3 bg-corp-accent2/10 border-corp-accent2/40 space-y-2">
                  <div className="text-[11px] uppercase tracking-wider text-corp-accent2">
                    Pending question
                  </div>
                  <p className="text-sm">{detail.pending_question}</p>
                  <textarea
                    className="jsp-input min-h-[80px] text-sm"
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    placeholder="Your answer…"
                    disabled={submittingAnswer}
                  />
                  <label className="text-[11px] flex items-center gap-1.5 text-corp-muted">
                    <input
                      type="checkbox"
                      className="accent-corp-accent"
                      checked={saveToBank}
                      onChange={(e) => setSaveToBank(e.target.checked)}
                    />
                    Save to answer bank for next time
                  </label>
                  <button
                    type="button"
                    className="jsp-btn-primary text-xs"
                    onClick={submitAnswer}
                    disabled={submittingAnswer || !answer.trim()}
                  >
                    {submittingAnswer ? "Submitting…" : "Submit answer + resume"}
                  </button>
                </div>
              ) : null}

              <div>
                <div className="text-[11px] uppercase tracking-wider text-corp-muted mb-1">
                  Transcript ({detail.steps.length} steps)
                </div>
                <ul className="divide-y divide-corp-border max-h-[60vh] overflow-y-auto">
                  {detail.steps.map((s) => (
                    <li key={s.id} className="py-2 flex gap-3 items-start">
                      <span className="text-[10px] uppercase tracking-wider text-corp-muted w-20 shrink-0">
                        {s.kind}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-[11px] text-corp-muted">
                          {new Date(s.ts).toLocaleTimeString()}
                        </div>
                        {s.payload ? (
                          <pre className="text-[11px] whitespace-pre-wrap font-mono bg-corp-surface2 rounded p-1 mt-1 max-h-40 overflow-y-auto">
                            {JSON.stringify(s.payload, null, 2)}
                          </pre>
                        ) : null}
                        {s.screenshot_url ? (
                          <a
                            href={s.screenshot_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[10px] text-corp-accent hover:underline"
                          >
                            View screenshot →
                          </a>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
    </PageShell>
  );
}
