"use client";

// Auto-apply controls + visibility heartbeat. Mounted inside the
// /browser page so the auto-pilot is gated on the user actually
// having the streamed browser visible. While the tab is visible we
// post a heartbeat to /api/v1/auto-apply/heartbeat every 10s; the
// poller refuses to fire runs unless it has a recent heartbeat.
//
// All policy controls live here (collapsed by default) so there's no
// separate /auto-apply page — the user can't enable auto-apply
// without being on the same page that proves the browser is visible.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

const HEARTBEAT_INTERVAL_MS = 10_000;

type Settings = {
  enabled: boolean;
  daily_cap: number;
  // Server still accepts these but the UI no longer touches them —
  // the only filter that matters is TrackedJob.status === "interested".
  min_fit_score: number | null;
  only_known_ats: boolean;
  pause_start_hour: number | null;
  pause_end_hour: number | null;
  last_run_at: string | null;
  last_browser_visible_at: string | null;
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
  in_flight: number;
  candidates: PreviewJob[];
};

const DEFAULT_DRAFT: Settings = {
  enabled: false,
  daily_cap: 5,
  min_fit_score: null,
  only_known_ats: false,
  pause_start_hour: null,
  pause_end_hour: null,
  last_run_at: null,
  last_browser_visible_at: null,
};

export function BrowserAutoApplyPanel() {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [draft, setDraft] = useState<Settings>(DEFAULT_DRAFT);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [heartbeatStatus, setHeartbeatStatus] = useState<"active" | "paused">(
    "paused",
  );
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- visibility heartbeat ------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function beat() {
      if (document.hidden) return;
      try {
        await api.post("/api/v1/auto-apply/heartbeat");
        if (!cancelled) setHeartbeatStatus("active");
      } catch {
        // Don't surface errors — heartbeat failures are common on
        // login expiry; the in-page status will show "paused" via
        // the visibilitychange handler.
      }
    }

    function startTimer() {
      if (heartbeatTimerRef.current) return;
      beat();
      heartbeatTimerRef.current = setInterval(beat, HEARTBEAT_INTERVAL_MS);
    }
    function stopTimer() {
      if (!heartbeatTimerRef.current) return;
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }

    function onVisibility() {
      if (document.hidden) {
        setHeartbeatStatus("paused");
        stopTimer();
      } else {
        startTimer();
      }
    }

    if (!document.hidden) {
      setHeartbeatStatus("active");
      startTimer();
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      stopTimer();
    };
  }, []);

  // ---- settings + preview --------------------------------------------------
  async function refresh() {
    try {
      const p = await api.get<Preview>("/api/v1/auto-apply/preview");
      setPreview(p);
      setDraft(p.settings);
      setErr(null);
    } catch (e) {
      const detail =
        e instanceof ApiError &&
        typeof e.detail === "object" &&
        e.detail !== null &&
        "detail" in (e.detail as Record<string, unknown>)
          ? String((e.detail as { detail: unknown }).detail)
          : null;
      setErr(
        detail
          ? detail
          : e instanceof ApiError
            ? `HTTP ${e.status}`
            : "Load failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // Poll fairly aggressively so the user sees in_flight / candidates
    // counts move within a few seconds of spawning runs.
    const t = setInterval(refresh, 5_000);
    return () => clearInterval(t);
  }, []);

  async function save(next: Settings) {
    setSaving(true);
    setMsg(null);
    setErr(null);
    try {
      await api.put("/api/v1/auto-apply/settings", next);
      await refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function toggle() {
    if (!preview) return;
    const next = { ...preview.settings, enabled: !preview.settings.enabled };
    await save(next);
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
      const detail =
        e instanceof ApiError &&
        typeof e.detail === "object" &&
        e.detail !== null &&
        "detail" in (e.detail as Record<string, unknown>)
          ? String((e.detail as { detail: unknown }).detail)
          : null;
      setErr(
        detail
          ? detail
          : e instanceof ApiError
            ? `HTTP ${e.status}`
            : "Run failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return (
      <div className="jsp-card p-3 text-sm text-corp-muted">
        Loading auto-apply…
      </div>
    );
  }

  const s = preview?.settings;
  const dirty = s !== undefined && draft.daily_cap !== s.daily_cap;

  return (
    <div className="jsp-card p-3 mb-3">
      <div className="flex flex-wrap items-center gap-3 mb-2">
        <div className="text-sm font-semibold uppercase tracking-wider">
          Auto-Apply
        </div>
        <span
          className={`text-[11px] uppercase tracking-wider px-1.5 py-0.5 rounded ${
            heartbeatStatus === "active"
              ? "bg-corp-ok/20 text-corp-ok"
              : "bg-corp-accent2/20 text-corp-accent2"
          }`}
          title={
            heartbeatStatus === "active"
              ? "This tab is visible — heartbeat is firing every 10s. The agent can run."
              : "Tab is hidden. Auto-apply is paused until you bring this tab back."
          }
        >
          {heartbeatStatus === "active" ? "Watching ✓" : "Paused — tab hidden"}
        </span>
        {s ? (
          <button
            className={`jsp-btn-ghost text-xs ${
              s.enabled
                ? "border-corp-ok text-corp-ok"
                : "border-corp-accent2 text-corp-accent2"
            }`}
            onClick={toggle}
          >
            {s.enabled ? "Enabled — click to disable" : "Disabled — click to enable"}
          </button>
        ) : null}
        <button
          type="button"
          className="text-xs text-corp-accent hover:underline ml-auto"
          onClick={() => setPolicyOpen((v) => !v)}
        >
          {policyOpen ? "Hide policy ▴" : "Tune policy ▾"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-corp-muted">
        <span>
          Today: <span className="text-corp-text">{preview?.used_today}</span> used /
          <span className="text-corp-text"> {s?.daily_cap}</span> cap
        </span>
        <span>
          In flight:{" "}
          <span className="text-corp-text">{preview?.in_flight ?? 0}</span>
        </span>
        <span>
          Eligible{" "}
          <span className="text-corp-muted">(status=interested)</span>:{" "}
          <span className="text-corp-text">
            {preview?.candidates.length ?? 0}
          </span>
        </span>
        <span>
          Last tick:{" "}
          <span className="text-corp-text">
            {s?.last_run_at ? new Date(s.last_run_at).toLocaleTimeString() : "never"}
          </span>
        </span>
        <button
          type="button"
          className="jsp-btn-ghost text-xs ml-auto"
          onClick={runNow}
          disabled={running || !s?.enabled || heartbeatStatus !== "active"}
          title={
            heartbeatStatus !== "active"
              ? "Bring this tab to the foreground first."
              : "Run a single tick now."
          }
        >
          {running ? "Running…" : "Run one tick now"}
        </button>
      </div>

      {msg ? <div className="text-[11px] text-corp-ok mt-2">{msg}</div> : null}
      {err ? <div className="text-[11px] text-corp-danger mt-2">{err}</div> : null}

      {policyOpen ? (
        <div className="mt-3 border-t border-corp-border pt-3 flex flex-wrap items-end gap-3 text-xs">
          <Field label="Daily cap" hint="Max submissions per UTC day. 0 disables.">
            <input
              type="number"
              min={0}
              max={100}
              value={draft.daily_cap}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  daily_cap: parseInt(e.target.value || "0", 10),
                })
              }
              className="jsp-input w-20"
            />
          </Field>
          <div className="text-corp-muted text-[11px] flex-1">
            Auto-apply scans every TrackedJob with{" "}
            <code className="text-corp-accent">status = &quot;interested&quot;</code>{" "}
            and a non-empty source URL. No fit-score / ATS gating —
            mark a job <i>interested</i> if and only if you want the agent
            to attempt it.
          </div>
          <button
            type="button"
            className="jsp-btn-ghost text-xs"
            onClick={() => preview && setDraft(preview.settings)}
            disabled={saving || !dirty}
          >
            Reset
          </button>
          <button
            type="button"
            className="jsp-btn text-xs"
            onClick={() => save(draft)}
            disabled={saving || !dirty}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      ) : null}

      {preview && preview.candidates.length > 0 ? (
        <details className="mt-2">
          <summary className="text-[11px] text-corp-muted cursor-pointer">
            Next-up: {preview.candidates.length} candidate
            {preview.candidates.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-1 text-[12px]">
            {preview.candidates.slice(0, 5).map((j) => (
              <li key={j.tracked_job_id} className="py-0.5">
                <Link
                  href={`/jobs/${j.tracked_job_id}`}
                  className="text-corp-accent hover:underline"
                >
                  {j.title}
                </Link>
                {j.organization ? ` · ${j.organization}` : ""}
                {j.fit_score !== null ? ` · fit ${j.fit_score}` : ""}
                {j.ats ? ` · ${j.ats}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
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
      <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
        {label}
      </div>
      {children}
      {hint ? (
        <div className="text-[10px] text-corp-muted mt-1">{hint}</div>
      ) : null}
    </div>
  );
}
