"use client";

// Settings → Sol Outbox: connect the private GitHub repo the Sol agent
// works from, set the reusable form answers (applicant.json), and watch
// the sync — approved jobs go to `main` as jobs/<slug>/ folders, Sol's
// status records come back from the `status` branch. The token is sent
// once, stored encrypted, and never shown again. Everything read back
// from the repo is rendered as plain text.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Applicant = {
  name?: string;
  email?: string;
  phone?: string;
  city_state?: string;
  links?: { linkedin?: string; github?: string; portfolio?: string };
  work_authorization?: string;
  needs_sponsorship?: boolean;
  earliest_start?: string;
  salary_expectation?: string;
  voluntary_disclosures?: "ask" | "decline";
};

type Report = {
  at: string;
  ok: boolean;
  error: string | null;
  status_branch: string | null;
  added: string[];
  updated: string[];
  withdrawn: string[];
  pushed_commits: number;
  status_applied: { slug: string; status: string }[];
  skipped_records: { file: string; reason: string }[];
  job_errors: { slug: string; error: string }[];
};

type Overview = {
  connected: boolean;
  repo: string | null;
  login: string | null;
  repo_private: boolean | null;
  connected_at: string | null;
  auto_approve: boolean;
  author_name: string;
  author_email: string;
  applicant: Applicant;
  last_sync_at: string | null;
  last_report: Report | null;
  running: boolean;
  sync_seconds: number;
  counts: Record<string, number>;
};

type OutboxRow = {
  id: number;
  job_id: number | null;
  slug: string;
  title: string | null;
  company: string | null;
  job_status: string | null;
  published_at: string | null;
  withdrawn_at: string | null;
  sol_status: string | null;
  sol_status_at: string | null;
  sol_confirmation: string | null;
  sol_note: string | null;
  last_error: string | null;
};

const TEXT_FIELDS: [keyof Applicant, string, string][] = [
  ["name", "Name", "Chris George"],
  ["email", "Email", "you@example.com"],
  ["phone", "Phone", ""],
  ["city_state", "City, State", "Columbus, OH"],
  ["work_authorization", "Work authorization", "US citizen"],
  ["earliest_start", "Earliest start", "Two weeks' notice"],
  ["salary_expectation", "Salary expectation", "$140k"],
];

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.info.message : fallback;
}

export function OutboxPanel() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [rows, setRows] = useState<OutboxRow[]>([]);
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [applicant, setApplicant] = useState<Applicant>({});
  const [author, setAuthor] = useState({ name: "", email: "" });

  const load = useCallback(async () => {
    try {
      const o = await api.get<Overview>("/api/v1/outbox");
      setOv(o);
      setRows(await api.get<OutboxRow[]>("/api/v1/outbox/jobs"));
      return o;
    } catch {
      setMsg("Couldn't load the outbox settings.");
      return null;
    }
  }, []);

  useEffect(() => {
    load().then((o) => {
      if (!o) return;
      setRepo(o.repo ?? "");
      setApplicant(o.applicant ?? {});
      setAuthor({ name: o.author_name, email: o.author_email });
    });
  }, [load]);

  useEffect(() => {
    if (!ov?.running) return;
    const t = setTimeout(load, 3000);
    return () => clearTimeout(t);
  }, [ov, load]);

  async function run(key: string, fn: () => Promise<Overview>, ok?: string) {
    setBusy(key);
    setMsg(null);
    try {
      setOv(await fn());
      if (ok) setMsg(ok);
    } catch (e) {
      setMsg(errText(e, "Request failed."));
    } finally {
      setBusy(null);
    }
  }

  if (!ov) {
    return <div className="jsp-card p-4 text-sm text-corp-muted">{msg ?? "Loading Sol outbox…"}</div>;
  }

  const r = ov.last_report;
  const setA = (k: keyof Applicant, v: unknown) => setApplicant((p) => ({ ...p, [k]: v }));
  const setLink = (k: "linkedin" | "github" | "portfolio", v: string) =>
    setApplicant((p) => ({ ...p, links: { ...(p.links ?? {}), [k]: v } }));

  return (
    <div className="space-y-4">
      {/* --- Connection ------------------------------------------------ */}
      <div className="jsp-card p-4 space-y-3">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">Sol outbox — GitHub connection</h3>
        <p className="text-xs text-corp-muted">
          Jobs you send to Sol are committed to <span className="font-mono">main</span> of a private repo
          (one commit per job: <span className="font-mono">jobs/&lt;slug&gt;/</span> with job.json, resume.pdf and
          the cover letter). Sol writes what it applied to on the <span className="font-mono">status</span>{" "}
          branch, which is read back every {Math.round(ov.sync_seconds / 60)} minutes and on demand — an{" "}
          <em>applied</em> record moves the job to Applied here. Use a dedicated GitHub account and a{" "}
          <strong>fine-grained personal access token</strong> limited to that one repo with{" "}
          <strong>Contents: read and write</strong> and nothing else.
        </p>
        {ov.connected ? (
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="px-2 py-0.5 rounded border border-green-500/40 bg-green-500/10 text-green-300">
              Connected as {ov.login}
            </span>
            <span className="font-mono">{ov.repo}</span>
            {ov.repo_private === false ? (
              <span className="text-xs text-corp-danger">This repo is PUBLIC — your resumes would be public. Make it private.</span>
            ) : null}
            <span className="text-xs text-corp-muted">since {when(ov.connected_at)}</span>
            <button
              className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40 ml-auto"
              disabled={busy !== null}
              onClick={() => {
                if (confirm("Disconnect? The token is forgotten and syncing stops. The repo and its history are untouched."))
                  run("disconnect", () => api.delete<Overview>("/api/v1/outbox/connect"), "Disconnected.");
              }}
            >
              Disconnect
            </button>
          </div>
        ) : null}
        <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto] items-end">
          <label className="text-xs text-corp-muted">
            Repository (owner/name)
            <input
              className="jsp-input text-sm mt-1 font-mono"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              placeholder="my-outbox-account/jobsearchpal-outbox"
            />
          </label>
          <label className="text-xs text-corp-muted">
            {ov.connected ? "Replace token" : "Personal access token"}
            <input
              className="jsp-input text-sm mt-1 font-mono"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="github_pat_…"
            />
          </label>
          <button
            className="jsp-btn-primary text-sm"
            disabled={busy !== null || !repo.trim() || !token.trim()}
            onClick={() =>
              run(
                "connect",
                async () => {
                  const o = await api.post<Overview>("/api/v1/outbox/connect", { repo, token });
                  setToken("");
                  await load();
                  return o;
                },
                "Connected — first sync is running.",
              )
            }
          >
            {busy === "connect" ? "Checking with GitHub…" : ov.connected ? "Reconnect" : "Connect"}
          </button>
        </div>
        {msg ? <div className="text-xs">{msg}</div> : null}
      </div>

      {/* --- Sync -------------------------------------------------------- */}
      <div className="jsp-card p-4 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">Sync</h3>
          <span className="text-xs text-corp-muted">
            {ov.running ? "Syncing now…" : `Last sync ${when(ov.last_sync_at)}`}
          </span>
          <span className="text-xs text-corp-muted">
            {ov.counts.published ?? 0} on the repo · {ov.counts.pending ?? 0} waiting · {ov.counts.applied ?? 0} applied by Sol ·{" "}
            {ov.counts.withdrawn ?? 0} withdrawn
          </span>
          <button
            className="jsp-btn-ghost text-xs ml-auto"
            disabled={!ov.connected || ov.running || busy !== null}
            onClick={() => run("sync", () => api.post<Overview>("/api/v1/outbox/sync"))}
          >
            Sync now
          </button>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={ov.auto_approve}
            disabled={busy !== null}
            onChange={(e) =>
              run("auto", () => api.put<Overview>("/api/v1/outbox/settings", { auto_approve: e.target.checked }))
            }
          />
          Auto-send every <em>Interested</em> job that has a tailored resume
          <span className="text-xs text-corp-muted">(otherwise use “Send to Sol” on a job or in the tracker’s bulk bar)</span>
        </label>
        {r ? (
          <div className="text-xs space-y-1">
            <div className={r.ok ? "text-corp-muted" : "text-corp-danger"}>
              {r.ok ? "OK" : "Failed"} · {when(r.at)} · {r.pushed_commits} commit(s) pushed · status branch:{" "}
              {r.status_branch === "missing"
                ? "not created yet (Sol makes it on its first write)"
                : r.status_branch === "unchanged"
                  ? "no new records"
                  : r.status_branch ?? "—"}
            </div>
            {r.error ? <pre className="whitespace-pre-wrap text-corp-danger">{r.error}</pre> : null}
            {r.added.length ? <div>Added: {r.added.join(", ")}</div> : null}
            {r.updated.length ? <div>Updated (regenerated docs): {r.updated.join(", ")}</div> : null}
            {r.withdrawn.length ? <div>Withdrawn: {r.withdrawn.join(", ")}</div> : null}
            {r.status_applied.length ? (
              <div>From Sol: {r.status_applied.map((s) => `${s.slug} → ${s.status}`).join(", ")}</div>
            ) : null}
            {r.job_errors.length ? (
              <div className="text-amber-300">
                Not sent: {r.job_errors.map((e) => `${e.slug}: ${e.error}`).join(" · ")}
              </div>
            ) : null}
            {r.skipped_records.length ? (
              <div className="text-amber-300">
                Ignored status files: {r.skipped_records.map((s) => `${s.file} (${s.reason})`).join(" · ")}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* --- applicant.json ---------------------------------------------------- */}
      <div className="jsp-card p-4 space-y-3">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">Standard answers for Sol (applicant.json)</h3>
        <p className="text-xs text-corp-muted">
          Committed to the repo so Sol can reuse them across forms. Every field is optional — leave out anything you
          want to be asked each time. Never put passwords, SSNs, dates of birth or bank details here (there are no
          fields for them, on purpose).
        </p>
        <div className="grid gap-2 md:grid-cols-2">
          {TEXT_FIELDS.map(([k, label, ph]) => (
            <label key={k} className="text-xs text-corp-muted">
              {label}
              <input
                className="jsp-input text-sm mt-1"
                value={(applicant[k] as string | undefined) ?? ""}
                placeholder={ph}
                onChange={(e) => setA(k, e.target.value)}
              />
            </label>
          ))}
          {(["linkedin", "github", "portfolio"] as const).map((k) => (
            <label key={k} className="text-xs text-corp-muted">
              {k === "linkedin" ? "LinkedIn URL" : k === "github" ? "GitHub URL" : "Portfolio URL"}
              <input
                className="jsp-input text-sm mt-1"
                value={applicant.links?.[k] ?? ""}
                onChange={(e) => setLink(k, e.target.value)}
              />
            </label>
          ))}
          <label className="text-xs text-corp-muted">
            Needs visa sponsorship
            <select
              className="jsp-input text-sm mt-1"
              value={applicant.needs_sponsorship === undefined ? "" : String(applicant.needs_sponsorship)}
              onChange={(e) => setA("needs_sponsorship", e.target.value === "" ? undefined : e.target.value === "true")}
            >
              <option value="">Ask me each time</option>
              <option value="false">No</option>
              <option value="true">Yes</option>
            </select>
          </label>
          <label className="text-xs text-corp-muted">
            Demographic / disability / veteran questions
            <select
              className="jsp-input text-sm mt-1"
              value={applicant.voluntary_disclosures ?? "ask"}
              onChange={(e) => setA("voluntary_disclosures", e.target.value)}
            >
              <option value="ask">Ask me</option>
              <option value="decline">Decline to answer</option>
            </select>
          </label>
          <label className="text-xs text-corp-muted">
            Commit author name
            <input
              className="jsp-input text-sm mt-1"
              value={author.name}
              placeholder="JobSearchPal"
              onChange={(e) => setAuthor((a) => ({ ...a, name: e.target.value }))}
            />
          </label>
          <label className="text-xs text-corp-muted">
            Commit author email
            <input
              className="jsp-input text-sm mt-1"
              value={author.email}
              placeholder={ov.login ? `${ov.login}@users.noreply.github.com` : "login@users.noreply.github.com"}
              onChange={(e) => setAuthor((a) => ({ ...a, email: e.target.value }))}
            />
          </label>
        </div>
        <button
          className="jsp-btn-primary text-sm"
          disabled={busy !== null}
          onClick={() =>
            run(
              "applicant",
              async () => {
                const o = await api.put<Overview>("/api/v1/outbox/settings", {
                  applicant,
                  author_name: author.name,
                  author_email: author.email,
                });
                setApplicant(o.applicant ?? {});
                return o;
              },
              ov.connected ? "Saved — applicant.json is committed on this sync." : "Saved.",
            )
          }
        >
          {busy === "applicant" ? "Saving…" : "Save answers"}
        </button>
      </div>

      {/* --- Jobs in the outbox ------------------------------------------------- */}
      <div className="jsp-card p-4">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">In the outbox ({rows.length})</h3>
        {rows.length === 0 ? (
          <p className="text-xs text-corp-muted">Nothing sent yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-corp-muted text-left">
                <tr>
                  <th className="py-1 pr-2">Job</th>
                  <th className="py-1 pr-2">Repo</th>
                  <th className="py-1 pr-2">Sol</th>
                  <th className="py-1">Details</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-corp-border align-top">
                    <td className="py-1 pr-2">
                      {row.job_id ? (
                        <Link href={`/jobs/${row.job_id}`} className="hover:text-corp-accent">
                          {row.title ?? row.slug}
                        </Link>
                      ) : (
                        <span className="text-corp-muted">{row.slug} (deleted)</span>
                      )}
                      {row.company ? <div className="text-corp-muted">{row.company}</div> : null}
                    </td>
                    <td className="py-1 pr-2 whitespace-nowrap">
                      {row.withdrawn_at ? "withdrawn" : row.published_at ? "pushed" : "waiting"}
                    </td>
                    <td className="py-1 pr-2 whitespace-nowrap">
                      {row.sol_status ?? "—"}
                      {row.sol_status_at ? <div className="text-corp-muted">{when(row.sol_status_at)}</div> : null}
                    </td>
                    <td className="py-1 break-words">
                      {row.last_error ? <div className="text-corp-danger">{row.last_error}</div> : null}
                      {row.sol_confirmation ? <div>Confirmation: {row.sol_confirmation}</div> : null}
                      {row.sol_note ? <div className="whitespace-pre-wrap">Note: {row.sol_note}</div> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
