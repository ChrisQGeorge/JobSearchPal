"use client";

// Sol outbox card on the job page: send this job (with its tailored resume
// + cover letter) to the Sol application agent's GitHub repo, withdraw it,
// and see what Sol reported back from the repo's `status` branch. Renders
// nothing until the outbox is connected in Settings → Sol Outbox. Sol's
// confirmation / note are untrusted text — rendered as plain text only.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

type OutboxEntry = {
  slug: string;
  notes: string | null;
  approved_at: string;
  published_at: string | null;
  withdrawn_at: string | null;
  withdraw_reason: string | null;
  sol_status: "applied" | "skipped" | "closed" | null;
  sol_status_at: string | null;
  sol_confirmation: string | null;
  sol_note: string | null;
  last_error: string | null;
};

type OutboxJobState = {
  connected: boolean;
  entry: OutboxEntry | null;
  blocked_reason: string | null;
  has_cover_letter: boolean;
  running: boolean;
  // Where Sol applies: the off-LinkedIn link for LinkedIn jobs, else the posting.
  apply_url: string | null;
};

const SOL_STYLE: Record<string, string> = {
  applied: "bg-green-500/15 text-green-300 border-green-500/40",
  skipped: "bg-corp-surface2 text-corp-muted border-corp-border",
  closed: "bg-amber-500/15 text-amber-300 border-amber-500/40",
};

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function SolOutboxCard({ jobId, onJobChanged }: { jobId: number; onJobChanged?: () => void }) {
  const [st, setSt] = useState<OutboxJobState | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSt(await api.get<OutboxJobState>(`/api/v1/outbox/jobs/${jobId}`));
    } catch {
      setSt(null);
    }
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load]);

  // While a sync runs, poll until it settles.
  useEffect(() => {
    if (!st?.running) return;
    const t = setTimeout(load, 3000);
    return () => clearTimeout(t);
  }, [st, load]);

  // A new Sol record may have moved the job (e.g. to Applied): refresh it.
  const solStatus = st?.entry?.sol_status ?? null;
  const seenSol = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (st === null) return;
    if (seenSol.current !== undefined && seenSol.current !== solStatus) onJobChanged?.();
    seenSol.current = solStatus;
  }, [st, solStatus, onJobChanged]);

  if (!st || !st.connected) return null;
  const e = st.entry;

  async function act(path: string, body: unknown) {
    setBusy(true);
    setMsg(null);
    try {
      setSt(await api.post<OutboxJobState>(path, body));
    } catch (err) {
      setMsg(err instanceof ApiError ? err.info.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  let stateLine: string;
  if (!e) stateLine = "Not sent to Sol.";
  else if (e.withdrawn_at) stateLine = `Withdrawn ${when(e.withdrawn_at)}${e.withdraw_reason ? ` — ${e.withdraw_reason}` : ""}`;
  else if (e.published_at) stateLine = `On the repo since ${when(e.published_at)}`;
  else stateLine = st.running ? "Committing and pushing…" : "Approved — waiting for the next sync to push.";

  return (
    <section className="jsp-card p-3 border-l-4 border-l-corp-accent space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium">Sol outbox</span>
        {e?.sol_status ? (
          <span className={`text-[11px] px-1.5 py-0.5 rounded border ${SOL_STYLE[e.sol_status]}`}>
            Sol: {e.sol_status}
            {e.sol_status_at ? ` · ${when(e.sol_status_at)}` : ""}
          </span>
        ) : null}
        <span className="text-xs text-corp-muted flex-1">{stateLine}</span>
        {e && !e.withdrawn_at && !e.sol_status ? (
          <button
            className="jsp-btn-ghost text-xs"
            disabled={busy}
            onClick={() => {
              const reason = prompt("Withdraw from Sol? Its folder gets withdrawn.json (nothing is deleted). Reason (optional):");
              if (reason !== null) act(`/api/v1/outbox/jobs/${jobId}/withdraw`, { reason });
            }}
          >
            Withdraw
          </button>
        ) : null}
      </div>

      {e?.slug ? <div className="text-[11px] text-corp-muted font-mono break-all">jobs/{e.slug}/</div> : null}
      {st.apply_url && !st.blocked_reason ? (
        <div className="text-[11px] text-corp-muted break-all">
          Sol applies at:{" "}
          <a href={st.apply_url} target="_blank" rel="noopener noreferrer" className="hover:text-corp-accent">
            {st.apply_url}
          </a>
        </div>
      ) : null}
      {e?.sol_confirmation ? (
        <div className="text-xs">
          <span className="text-corp-muted">Confirmation: </span>
          {e.sol_confirmation}
        </div>
      ) : null}
      {e?.sol_note ? (
        <div className="text-xs whitespace-pre-wrap">
          <span className="text-corp-muted">Sol’s note: </span>
          {e.sol_note}
        </div>
      ) : null}
      {e?.notes ? (
        <div className="text-xs whitespace-pre-wrap">
          <span className="text-corp-muted">Your notes for Sol: </span>
          {e.notes}
        </div>
      ) : null}
      {e?.last_error ? <div className="text-xs text-corp-danger whitespace-pre-wrap">{e.last_error}</div> : null}

      {!e ? (
        <div className="flex gap-2 items-start flex-wrap">
          <input
            className="jsp-input text-sm flex-1 min-w-[220px]"
            placeholder="Notes for Sol (optional) — e.g. “use the portfolio link”, “salary: 140k”"
            value={notes}
            onChange={(ev) => setNotes(ev.target.value)}
            disabled={busy || !!st.blocked_reason}
          />
          <button
            className="jsp-btn-primary text-sm"
            disabled={busy || !!st.blocked_reason}
            title={st.blocked_reason ?? "Commit this job with its resume and cover letter to the outbox repo"}
            onClick={() => act(`/api/v1/outbox/jobs/${jobId}/approve`, { notes: notes.trim() || null })}
          >
            {busy ? "Sending…" : "Send to Sol"}
          </button>
        </div>
      ) : null}
      {!e && st.blocked_reason ? <div className="text-xs text-amber-300">{st.blocked_reason}</div> : null}
      {!e && !st.blocked_reason && !st.has_cover_letter ? (
        <div className="text-[11px] text-corp-muted">No cover letter for this job — Sol gets the resume only.</div>
      ) : null}
      {msg ? <div className="text-xs text-corp-danger">{msg}</div> : null}
    </section>
  );
}
