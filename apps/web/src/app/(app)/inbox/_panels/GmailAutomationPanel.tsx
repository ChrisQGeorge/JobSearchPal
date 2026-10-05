"use client";

// Gmail connection + automation rules for the Email Inbox page. The
// mailbox is read over IMAP with a Google app password (read-only —
// nothing is marked read or moved); notifications go out over Gmail
// SMTP with the same password.

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Rule = { set_status: boolean; notify: boolean };

type Automation = {
  enabled: boolean;
  username: string;
  folder: string;
  poll_minutes: number;
  lookback_days: number;
  notify_to: string;
  min_confidence_status: number;
  min_confidence_notify: number;
  uncertain_below: number;
  rules: Record<string, Rule>;
  intent_labels: Record<string, string>;
  has_password: boolean;
  state: {
    last_poll_at?: string;
    last_error?: string | null;
    last_counts?: {
      fetched: number;
      queued: number;
      skipped: number;
      duplicates: number;
      remaining: number;
    };
  };
};

type TestOut = {
  imap?: { ok: boolean; detail: string };
  smtp?: { ok: boolean; detail: string };
};

export function GmailAutomationPanel({ onPolled }: { onPolled: () => void }) {
  const [cfg, setCfg] = useState<Automation | null>(null);
  const [password, setPassword] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<null | "save" | "test" | "poll">(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [test, setTest] = useState<TestOut | null>(null);

  useEffect(() => {
    api
      .get<Automation>("/api/v1/email-ingest/automation")
      .then((c) => {
        setCfg(c);
        if (!c.username) setOpen(true);
      })
      .catch(() => setMsg("Could not load Gmail settings."));
  }, []);

  if (!cfg) {
    return msg ? <div className="jsp-card p-3 mb-4 text-xs text-corp-danger">{msg}</div> : null;
  }

  function set<K extends keyof Automation>(k: K, v: Automation[K]) {
    setCfg((c) => (c ? { ...c, [k]: v } : c));
  }
  function setRule(intent: string, patch: Partial<Rule>) {
    setCfg((c) =>
      c ? { ...c, rules: { ...c.rules, [intent]: { ...c.rules[intent], ...patch } } } : c,
    );
  }

  async function save() {
    if (!cfg) return;
    setBusy("save");
    setMsg(null);
    try {
      const out = await api.put<Automation>("/api/v1/email-ingest/automation", {
        enabled: cfg.enabled,
        username: cfg.username,
        folder: cfg.folder,
        poll_minutes: cfg.poll_minutes,
        lookback_days: cfg.lookback_days,
        notify_to: cfg.notify_to,
        min_confidence_status: cfg.min_confidence_status,
        min_confidence_notify: cfg.min_confidence_notify,
        uncertain_below: cfg.uncertain_below,
        rules: cfg.rules,
        app_password: password || null,
      });
      setCfg(out);
      setPassword("");
      setMsg("Saved.");
    } catch (e) {
      setMsg(e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.");
    } finally {
      setBusy(null);
    }
  }

  async function runTest() {
    setBusy("test");
    setTest(null);
    try {
      setTest(await api.post<TestOut>("/api/v1/email-ingest/automation/test", {}));
    } catch (e) {
      setMsg(e instanceof ApiError ? `Test failed (HTTP ${e.status}) — save first.` : "Test failed.");
    } finally {
      setBusy(null);
    }
  }

  async function pollNow() {
    setBusy("poll");
    setMsg(null);
    try {
      const out = await api.post<{
        fetched?: number;
        queued?: number;
        skipped?: number;
        error?: string;
      }>("/api/v1/email-ingest/automation/poll-now", {});
      setMsg(
        out.error
          ? `Poll failed: ${out.error}`
          : `Checked ${out.fetched ?? 0} new message(s): ${out.queued ?? 0} queued for classification, ${out.skipped ?? 0} skipped as not job-related.`,
      );
      const c = await api.get<Automation>("/api/v1/email-ingest/automation");
      setCfg(c);
      onPolled();
    } catch (e) {
      setMsg(e instanceof ApiError ? `Poll failed (HTTP ${e.status}).` : "Poll failed.");
    } finally {
      setBusy(null);
    }
  }

  const st = cfg.state ?? {};
  const statusLine = !cfg.username
    ? "Not connected"
    : !cfg.enabled
      ? "Connected — automatic polling off"
      : st.last_error
        ? `Error: ${st.last_error}`
        : st.last_poll_at
          ? `Watching ${cfg.username} · last checked ${new Date(st.last_poll_at).toLocaleString()}`
          : `Watching ${cfg.username} · first check within a minute`;

  return (
    <section className="jsp-card p-4 mb-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">Gmail</h3>
        <span
          className={`text-xs ${st.last_error ? "text-corp-danger" : "text-corp-muted"} truncate max-w-full`}
        >
          {statusLine}
        </span>
        <div className="ml-auto flex gap-2">
          {cfg.username ? (
            <button
              type="button"
              className="jsp-btn-ghost text-xs"
              onClick={() => void pollNow()}
              disabled={busy !== null}
            >
              {busy === "poll" ? "Checking…" : "Check now"}
            </button>
          ) : null}
          <button type="button" className="jsp-btn-ghost text-xs" onClick={() => setOpen((o) => !o)}>
            {open ? "Hide settings" : "Settings"}
          </button>
        </div>
      </div>

      {open ? (
        <div className="space-y-4">
          <p className="text-[11px] text-corp-muted">
            Uses a Google <strong>app password</strong> (Google Account → Security → 2-Step
            Verification → App passwords), not your normal password. Mail is read-only: nothing
            is marked read, moved, or deleted. Only emails that mention a tracked company or
            contain hiring language are sent to the classifier.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="jsp-label">Gmail address</label>
              <input
                className="jsp-input"
                value={cfg.username}
                onChange={(e) => set("username", e.target.value)}
                placeholder="you@gmail.com"
              />
            </div>
            <div>
              <label className="jsp-label">
                App password {cfg.has_password ? "(saved — leave blank to keep)" : ""}
              </label>
              <input
                className="jsp-input"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={cfg.has_password ? "••••••••••••••••" : "abcd efgh ijkl mnop"}
              />
            </div>
            <div>
              <label className="jsp-label">Folder / label</label>
              <input
                className="jsp-input"
                value={cfg.folder}
                onChange={(e) => set("folder", e.target.value)}
                placeholder="INBOX"
              />
            </div>
            <div>
              <label className="jsp-label">Send alerts to (personal address)</label>
              <input
                className="jsp-input"
                value={cfg.notify_to}
                onChange={(e) => set("notify_to", e.target.value)}
                placeholder="me@personal.com"
              />
            </div>
            <div>
              <label className="jsp-label">Check every (minutes)</label>
              <input
                className="jsp-input"
                type="number"
                min={1}
                max={1440}
                value={cfg.poll_minutes}
                onChange={(e) => set("poll_minutes", Math.max(1, Number(e.target.value) || 10))}
              />
            </div>
            <div>
              <label className="jsp-label">On first connect, look back (days)</label>
              <input
                className="jsp-input"
                type="number"
                min={1}
                max={60}
                value={cfg.lookback_days}
                onChange={(e) => set("lookback_days", Math.max(1, Number(e.target.value) || 3))}
              />
            </div>
          </div>

          <div>
            <div className="jsp-label mb-1">What to do automatically</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-corp-muted">
                    <th className="py-1 pr-3 font-normal">Email type</th>
                    <th className="py-1 pr-3 font-normal">Update job status</th>
                    <th className="py-1 font-normal">Email me</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(cfg.rules).map(([intent, r]) => (
                    <tr key={intent} className="border-t border-corp-border">
                      <td className="py-1.5 pr-3">{cfg.intent_labels[intent] ?? intent}</td>
                      <td className="py-1.5 pr-3">
                        {intent === "uncertain" ? (
                          <span
                            className="text-corp-muted"
                            title="Unclear emails never change a status — you classify them."
                          >
                            —
                          </span>
                        ) : (
                          <input
                            type="checkbox"
                            className="accent-corp-accent h-4 w-4"
                            checked={r.set_status}
                            onChange={(e) => setRule(intent, { set_status: e.target.checked })}
                            aria-label={`Update status for ${intent}`}
                          />
                        )}
                      </td>
                      <td className="py-1.5">
                        <input
                          type="checkbox"
                          className="accent-corp-accent h-4 w-4"
                          checked={r.notify}
                          onChange={(e) => setRule(intent, { notify: e.target.checked })}
                          aria-label={`Email me for ${intent}`}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-corp-muted mt-1">
              Status changes need a matched tracked job and at least{" "}
              <input
                type="number"
                min={0}
                max={100}
                className="jsp-input inline-block w-14 text-xs py-0 px-1"
                value={Math.round(cfg.min_confidence_status * 100)}
                onChange={(e) =>
                  set("min_confidence_status", Math.min(1, Math.max(0, Number(e.target.value) / 100)))
                }
              />
              % classifier confidence; alerts need{" "}
              <input
                type="number"
                min={0}
                max={100}
                className="jsp-input inline-block w-14 text-xs py-0 px-1"
                value={Math.round(cfg.min_confidence_notify * 100)}
                onChange={(e) =>
                  set("min_confidence_notify", Math.min(1, Math.max(0, Number(e.target.value) / 100)))
                }
              />
              %. Jobs marked won or withdrawn are never changed. Everything still lands in the
              inbox below for review.
            </p>
            <p className="text-[11px] text-corp-muted mt-1">
              Treat an email as <strong>unclear</strong> when the classifier is under{" "}
              <input
                type="number"
                min={0}
                max={100}
                className="jsp-input inline-block w-14 text-xs py-0 px-1"
                value={Math.round(cfg.uncertain_below * 100)}
                onChange={(e) =>
                  set("uncertain_below", Math.min(1, Math.max(0, Number(e.target.value) / 100)))
                }
              />
              % sure — nothing happens automatically, it&apos;s flagged in the inbox for you to
              classify, and (if &quot;Email me&quot; is ticked) you get a link to it.
            </p>
          </div>

          <label className="text-xs flex items-center gap-1.5">
            <input
              type="checkbox"
              className="accent-corp-accent"
              checked={cfg.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
            />
            Check Gmail automatically
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="jsp-btn-primary"
              onClick={() => void save()}
              disabled={busy !== null}
            >
              {busy === "save" ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              className="jsp-btn-ghost"
              onClick={() => void runTest()}
              disabled={busy !== null || !cfg.username}
              title="Log in to Gmail and send a test alert to your personal address"
            >
              {busy === "test" ? "Testing…" : "Test connection"}
            </button>
          </div>
          {test ? (
            <div className="text-xs space-y-0.5">
              {test.imap ? (
                <div className={test.imap.ok ? "text-corp-ok" : "text-corp-danger"}>
                  Reading mail: {test.imap.detail}
                </div>
              ) : null}
              {test.smtp ? (
                <div className={test.smtp.ok ? "text-corp-ok" : "text-corp-danger"}>
                  Sending alerts: {test.smtp.detail}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
      {msg ? <p className="text-xs text-corp-muted">{msg}</p> : null}
    </section>
  );
}
