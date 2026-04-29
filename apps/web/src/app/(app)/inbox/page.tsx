"use client";

// Email inbox: paste a job-related email, the Companion classifies it
// and proposes a tracked-job match + status change. The user confirms
// (or overrides) before anything mutates a TrackedJob.
//
// Two panes: a paste form on top, a list of previously-parsed emails
// below. Selecting a parsed row opens the review panel.

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";
import { type JobStatus, type TrackedJobSummary } from "@/lib/types";

type Classification = {
  intent?: string;
  confidence?: number;
  matched_job_id?: number | null;
  matched_reason?: string;
  suggested_status?: string | null;
  suggested_event_type?: string | null;
  key_dates?: string[];
  summary?: string;
};

type ParsedEmail = {
  id: number;
  from_address: string | null;
  subject: string | null;
  received_at: string | null;
  body_md: string | null;
  classification: Classification | null;
  tracked_job_id: number | null;
  state: "new" | "applied" | "dismissed" | "errored";
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

const ALLOWED_STATUSES: JobStatus[] = [
  "applied",
  "screening",
  "interviewing",
  "assessment",
  "offer",
  "won",
  "lost",
  "withdrawn",
  "ghosted",
  "responded",
  "not_interested",
];

const STATE_LABELS: Record<ParsedEmail["state"], string> = {
  new: "Awaiting review",
  applied: "Applied",
  dismissed: "Dismissed",
  errored: "Parse failed",
};

export default function EmailInboxPage() {
  const [items, setItems] = useState<ParsedEmail[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<"all" | ParsedEmail["state"]>("new");

  // Paste form
  const [from, setFrom] = useState("");
  const [subject, setSubject] = useState("");
  const [received, setReceived] = useState("");
  const [body, setBody] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseErr, setParseErr] = useState<string | null>(null);

  // Selection
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [jobs, setJobs] = useState<TrackedJobSummary[]>([]);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const params = new URLSearchParams();
      if (stateFilter !== "all") params.set("state", stateFilter);
      const rows = await api.get<ParsedEmail[]>(
        `/api/v1/email-ingest?${params.toString()}`,
      );
      setItems(rows);
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

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateFilter]);

  useEffect(() => {
    api
      .get<TrackedJobSummary[]>("/api/v1/jobs")
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  async function parsePaste() {
    if (!body.trim()) {
      setParseErr("Body is required.");
      return;
    }
    setParsing(true);
    setParseErr(null);
    try {
      const out = await api.post<ParsedEmail>("/api/v1/email-ingest/parse", {
        from_address: from.trim() || null,
        subject: subject.trim() || null,
        received_at: received ? new Date(received).toISOString() : null,
        body: body.trim(),
      });
      setFrom("");
      setSubject("");
      setReceived("");
      setBody("");
      setStateFilter("new");
      await refresh();
      setSelectedId(out.id);
    } catch (e) {
      setParseErr(
        e instanceof ApiError
          ? `Parse failed (HTTP ${e.status}).`
          : "Parse failed.",
      );
    } finally {
      setParsing(false);
    }
  }

  const selected = items.find((i) => i.id === selectedId) ?? null;

  return (
    <PageShell
      title="Email Inbox"
      subtitle="Paste a job-related email and the Companion will tell you which tracked job it touches and what status to move it to. You always confirm before anything mutates."
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger mb-3">{err}</div>
      ) : null}

      <section className="jsp-card p-4 space-y-3 mb-4">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">
          Parse new email
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">From</label>
            <input
              className="jsp-input"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              placeholder="recruiter@acme.com"
            />
          </div>
          <div>
            <label className="jsp-label">Subject</label>
            <input
              className="jsp-input"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Update on your application"
            />
          </div>
          <div>
            <label className="jsp-label">Received (optional)</label>
            <input
              type="datetime-local"
              className="jsp-input"
              value={received}
              onChange={(e) => setReceived(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className="jsp-label">Body (raw text or markdown)</label>
          <textarea
            className="jsp-input font-mono text-sm min-h-[160px]"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Paste the full email body here, including any quoted thread."
            disabled={parsing}
          />
        </div>
        <div className="flex gap-2 items-center">
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={parsePaste}
            disabled={parsing || !body.trim()}
          >
            {parsing ? "Parsing…" : "Parse with Companion"}
          </button>
          {parseErr ? (
            <span className="text-xs text-corp-danger">{parseErr}</span>
          ) : null}
          <span className="text-[11px] text-corp-muted ml-auto">
            Duplicate emails (same from / subject / body) collapse onto a
            single row. Use Re-parse on the row to retry classification.
          </span>
        </div>
      </section>

      <section className="jsp-card p-4">
        <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Inbox
          </h3>
          <div className="flex gap-1.5">
            {(["new", "applied", "dismissed", "errored", "all"] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => {
                  setStateFilter(s);
                  setSelectedId(null);
                }}
                className={`px-2 py-0.5 rounded-md text-xs uppercase tracking-wider border ${
                  stateFilter === s
                    ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
                    : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {loading ? (
          <p className="text-corp-muted text-sm">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-corp-muted">
            {stateFilter === "new"
              ? "Inbox zero. Paste an email above to start."
              : "No emails in this filter."}
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-3">
            <ul className="divide-y divide-corp-border">
              {items.map((it) => (
                <li
                  key={it.id}
                  className={`py-2 px-2 cursor-pointer ${
                    selectedId === it.id
                      ? "bg-corp-accent/10"
                      : "hover:bg-corp-surface2"
                  }`}
                  onClick={() => setSelectedId(it.id)}
                >
                  <div className="text-sm truncate">
                    {it.subject || "(no subject)"}
                  </div>
                  <div className="text-[11px] text-corp-muted truncate">
                    {[
                      it.from_address,
                      it.classification?.intent,
                      STATE_LABELS[it.state],
                      new Date(
                        it.received_at ?? it.created_at,
                      ).toLocaleDateString(),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </li>
              ))}
            </ul>
            <div>
              {selected ? (
                <ReviewPanel
                  email={selected}
                  jobs={jobs}
                  onUpdated={async () => {
                    await refresh();
                  }}
                />
              ) : (
                <p className="text-corp-muted text-sm">
                  Select a row to review the classifier output.
                </p>
              )}
            </div>
          </div>
        )}
      </section>
    </PageShell>
  );
}

function ReviewPanel({
  email,
  jobs,
  onUpdated,
}: {
  email: ParsedEmail;
  jobs: TrackedJobSummary[];
  onUpdated: () => void | Promise<void>;
}) {
  const cls = email.classification ?? {};
  const [overrideJobId, setOverrideJobId] = useState<number | "none">(
    email.tracked_job_id ?? cls.matched_job_id ?? "none",
  );
  const [overrideStatus, setOverrideStatus] = useState<string>(
    cls.suggested_status ?? "",
  );
  const [overrideEventType, setOverrideEventType] = useState<string>(
    cls.suggested_event_type ?? "note",
  );
  const [overrideNotes, setOverrideNotes] = useState<string>(cls.summary ?? "");
  const [busy, setBusy] = useState<"none" | "apply" | "dismiss" | "reparse" | "delete">(
    "none",
  );
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setOverrideJobId(email.tracked_job_id ?? email.classification?.matched_job_id ?? "none");
    setOverrideStatus(email.classification?.suggested_status ?? "");
    setOverrideEventType(email.classification?.suggested_event_type ?? "note");
    setOverrideNotes(email.classification?.summary ?? "");
  }, [email.id, email.tracked_job_id, email.classification]);

  const matchedJob = useMemo(
    () =>
      jobs.find((j) => j.id === email.tracked_job_id) ??
      jobs.find((j) => j.id === email.classification?.matched_job_id) ??
      null,
    [jobs, email.tracked_job_id, email.classification],
  );

  async function apply() {
    setBusy("apply");
    setErr(null);
    try {
      await api.post(`/api/v1/email-ingest/${email.id}/apply`, {
        tracked_job_id: overrideJobId === "none" ? null : overrideJobId,
        new_status: overrideStatus || null,
        event_type: overrideEventType || null,
        notes: overrideNotes || null,
      });
      await onUpdated();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Apply failed (HTTP ${e.status}).`
          : "Apply failed.",
      );
    } finally {
      setBusy("none");
    }
  }

  async function dismiss() {
    setBusy("dismiss");
    setErr(null);
    try {
      await api.post(`/api/v1/email-ingest/${email.id}/dismiss`, {});
      await onUpdated();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Dismiss failed (HTTP ${e.status}).`
          : "Dismiss failed.",
      );
    } finally {
      setBusy("none");
    }
  }

  async function reparse() {
    setBusy("reparse");
    setErr(null);
    try {
      await api.post(`/api/v1/email-ingest/${email.id}/reparse`, {});
      await onUpdated();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Reparse failed (HTTP ${e.status}).`
          : "Reparse failed.",
      );
    } finally {
      setBusy("none");
    }
  }

  async function remove() {
    if (!confirm("Delete this parsed email permanently?")) return;
    setBusy("delete");
    setErr(null);
    try {
      await api.delete(`/api/v1/email-ingest/${email.id}`);
      await onUpdated();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Delete failed (HTTP ${e.status}).`
          : "Delete failed.",
      );
    } finally {
      setBusy("none");
    }
  }

  const intent = cls.intent ?? "unknown";
  const intentTone =
    intent === "rejection" || intent === "ghosted"
      ? "text-corp-danger"
      : intent === "offer" || intent === "interview_invite"
        ? "text-emerald-300"
        : intent === "take_home_assigned"
          ? "text-corp-accent2"
          : "text-corp-muted";

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span
          className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${intentTone} bg-corp-surface2 border-corp-border`}
        >
          {intent}
        </span>
        {typeof cls.confidence === "number" ? (
          <span className="text-[10px] text-corp-muted">
            confidence {Math.round((cls.confidence ?? 0) * 100)}%
          </span>
        ) : null}
        <span className="text-[10px] text-corp-muted ml-auto">
          {STATE_LABELS[email.state]}
        </span>
      </div>
      {email.error_message ? (
        <div className="text-xs text-corp-danger">{email.error_message}</div>
      ) : null}
      {cls.summary ? (
        <p className="text-sm">{cls.summary}</p>
      ) : null}
      {cls.matched_reason ? (
        <p className="text-[11px] text-corp-muted italic">
          Match reasoning: {cls.matched_reason}
        </p>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Tracked job</label>
          <select
            className="jsp-input"
            value={overrideJobId}
            onChange={(e) =>
              setOverrideJobId(
                e.target.value === "none" ? "none" : Number(e.target.value),
              )
            }
          >
            <option value="none">— No tracked job (just dismiss)</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}
                {j.organization_name ? ` · ${j.organization_name}` : ""}
              </option>
            ))}
          </select>
          {matchedJob ? (
            <Link
              href={`/jobs/${matchedJob.id}`}
              className="text-[10px] text-corp-accent hover:underline mt-1 inline-block"
            >
              Open tracked job →
            </Link>
          ) : null}
        </div>
        <div>
          <label className="jsp-label">New status</label>
          <select
            className="jsp-input"
            value={overrideStatus}
            onChange={(e) => setOverrideStatus(e.target.value)}
          >
            <option value="">— No status change</option>
            {ALLOWED_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Event type</label>
          <input
            className="jsp-input"
            value={overrideEventType}
            onChange={(e) => setOverrideEventType(e.target.value)}
            placeholder="note / rejection / interview_scheduled"
          />
        </div>
        <div>
          <label className="jsp-label">Activity-feed note</label>
          <input
            className="jsp-input"
            value={overrideNotes}
            onChange={(e) => setOverrideNotes(e.target.value)}
          />
        </div>
      </div>

      {cls.key_dates && cls.key_dates.length > 0 ? (
        <div className="text-[11px] text-corp-muted">
          Key dates pulled from body:{" "}
          {cls.key_dates.map((d, i) => (
            <span key={i} className="mr-1.5">
              {d}
            </span>
          ))}
        </div>
      ) : null}

      {email.body_md ? (
        <details>
          <summary className="text-[11px] text-corp-muted cursor-pointer">
            Show email body
          </summary>
          <pre className="text-[11px] whitespace-pre-wrap text-corp-muted font-sans max-h-72 overflow-y-auto mt-2 p-2 bg-corp-surface2 rounded border border-corp-border">
            {email.body_md}
          </pre>
        </details>
      ) : null}

      <div className="flex gap-2 flex-wrap">
        <button
          type="button"
          className="jsp-btn-primary text-xs"
          onClick={apply}
          disabled={busy !== "none" || email.state === "applied"}
        >
          {busy === "apply" ? "Applying…" : "Apply"}
        </button>
        <button
          type="button"
          className="jsp-btn-ghost text-xs"
          onClick={dismiss}
          disabled={busy !== "none" || email.state === "dismissed"}
        >
          Dismiss
        </button>
        <button
          type="button"
          className="jsp-btn-ghost text-xs"
          onClick={reparse}
          disabled={busy !== "none"}
          title="Re-run the classifier"
        >
          {busy === "reparse" ? "…" : "Re-parse"}
        </button>
        <button
          type="button"
          className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40 ml-auto"
          onClick={remove}
          disabled={busy !== "none"}
        >
          Delete
        </button>
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
    </div>
  );
}
