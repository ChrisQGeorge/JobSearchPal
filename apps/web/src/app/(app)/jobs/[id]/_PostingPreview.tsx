"use client";

// Posting preview on the job detail page. Loads automatically when the
// page opens: the server fetches the apply link (most job boards refuse
// to be framed, so a bare <iframe> would usually be blank), finds the
// work-arrangement wording, and returns a readable copy. When the site
// does allow framing, the live page can be shown too.

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Arrangement = "onsite" | "hybrid" | "remote" | "mixed" | null;

type Preview = {
  url: string;
  final_url: string;
  status: number;
  ok: boolean;
  embeddable: boolean;
  frame_reason: string;
  text: string;
  thin: boolean;
  arrangement: { guess: Arrangement; signals: Partial<Record<"onsite" | "hybrid" | "remote", string[]>> };
  job_remote_policy: string | null;
  cached: boolean;
};

const LABEL: Record<string, string> = {
  onsite: "On-site",
  hybrid: "Hybrid",
  remote: "Remote",
  mixed: "Mixed signals",
};
const TONE: Record<string, string> = {
  onsite: "border-corp-danger/50 bg-corp-danger/10 text-corp-danger",
  hybrid: "border-corp-accent2/50 bg-corp-accent2/10 text-corp-accent2",
  remote: "border-corp-ok/50 bg-corp-ok/10 text-corp-ok",
  mixed: "border-corp-accent2/50 bg-corp-accent2/10 text-corp-accent2",
};
const COLLAPSE_KEY = "jsp:posting-preview:collapsed";

export function PostingPreview({
  jobId,
  sourceUrl,
  remotePolicy,
  onSetRemotePolicy,
}: {
  jobId: number;
  sourceUrl: string | null | undefined;
  remotePolicy: string | null | undefined;
  onSetRemotePolicy: (p: "onsite" | "hybrid" | "remote") => void;
}) {
  const [data, setData] = useState<Preview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"text" | "page">("text");
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage blocked */
    }
  }, []);

  async function load(refresh = false) {
    if (!sourceUrl) return;
    setLoading(true);
    setErr(null);
    try {
      const d = await api.get<Preview>(
        `/api/v1/jobs/${jobId}/posting-preview${refresh ? "?refresh=true" : ""}`,
      );
      setData(d);
      setView(d.embeddable && (d.thin || !d.text.trim()) ? "page" : "text");
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? (typeof e.detail === "string" ? e.detail : e.info?.message) || `HTTP ${e.status}`
          : "Couldn't load the posting.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setData(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, sourceUrl]);

  if (!sourceUrl) return null;

  function toggle() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  }

  const guess = data?.arrangement.guess ?? null;
  const listed = (remotePolicy ?? "").toLowerCase() || null;
  const mismatch =
    guess && guess !== "mixed" && listed && listed !== guess ? guess : null;

  return (
    <section className="jsp-card p-3 mb-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={toggle} className="text-sm font-medium hover:text-corp-accent">
          {collapsed ? "▸" : "▾"} Posting
        </button>
        {loading ? (
          <span className="text-[11px] text-corp-muted">loading the posting…</span>
        ) : data ? (
          <span
            className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded-full border ${
              guess ? TONE[guess] : "border-corp-border text-corp-muted"
            }`}
            title="Work arrangement detected in the posting's text"
          >
            {guess ? `Posting says: ${LABEL[guess]}` : "Arrangement not stated"}
          </span>
        ) : null}
        {mismatch ? (
          <span className="text-[11px] text-corp-danger">
            Job is saved as <b>{listed}</b>
          </span>
        ) : null}
        {data && guess === "mixed" ? (
          <span className="text-[11px] text-corp-muted">set it yourself:</span>
        ) : null}
        {data && (mismatch || guess === "mixed")
          ? (["onsite", "hybrid", "remote"] as const)
              .filter((p) => p !== listed)
              .map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`jsp-btn-ghost text-[11px] py-0.5 ${p === mismatch ? "border-corp-accent text-corp-accent" : ""}`}
                  onClick={() => onSetRemotePolicy(p)}
                  title={`Save this job's remote policy as ${p}`}
                >
                  Set {LABEL[p].toLowerCase()}
                </button>
              ))
          : null}
        <span className="ml-auto flex gap-1.5 items-center">
          {data?.embeddable ? (
            <span className="flex rounded border border-corp-border overflow-hidden text-[11px]">
              {(["text", "page"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => {
                    setView(v);
                    setCollapsed(false);
                  }}
                  className={`px-2 py-0.5 ${view === v ? "bg-corp-accent/20 text-corp-accent" : "text-corp-muted"}`}
                >
                  {v === "text" ? "Text" : "Live page"}
                </button>
              ))}
            </span>
          ) : null}
          <button
            type="button"
            className="jsp-btn-ghost text-[11px] py-0.5"
            onClick={() => void load(true)}
            disabled={loading}
            title="Fetch the posting again"
          >
            Refresh
          </button>
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="jsp-btn-ghost text-[11px] py-0.5"
          >
            Open ↗
          </a>
        </span>
      </div>

      {err ? (
        <p className="text-[11px] text-corp-danger whitespace-pre-wrap">
          {err} Use “Open ↗” to view it on the site.
        </p>
      ) : null}

      {data && !collapsed ? (
        <>
          {Object.entries(data.arrangement.signals).length ? (
            <ul className="text-[11px] space-y-0.5">
              {(["onsite", "hybrid", "remote"] as const).flatMap((k) =>
                (data.arrangement.signals[k] ?? []).map((snip, i) => (
                  <li key={`${k}-${i}`} className="flex gap-2">
                    <span
                      className={`shrink-0 text-[9px] uppercase tracking-wider px-1 rounded border h-fit ${TONE[k]}`}
                    >
                      {LABEL[k]}
                    </span>
                    <span className="text-corp-text/80">“{snip}”</span>
                  </li>
                )),
              )}
            </ul>
          ) : null}
          {!data.ok ? (
            <p className="text-[11px] text-corp-danger">
              The site answered HTTP {data.status} — the posting may be closed or behind a login.
            </p>
          ) : data.thin ? (
            <p className="text-[11px] text-corp-muted">
              The site returned almost no readable text (it builds the page with JavaScript or
              blocks automated viewers){data.embeddable ? " — showing the live page instead." : " — use “Open ↗”."}
            </p>
          ) : null}
          {view === "page" && data.embeddable ? (
            <iframe
              src={data.final_url}
              className="w-full h-[70vh] rounded border border-corp-border bg-white"
              sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
              referrerPolicy="no-referrer"
              title="Job posting"
            />
          ) : data.text.trim() ? (
            <div className="max-h-[50vh] overflow-y-auto rounded border border-corp-border p-3 text-xs whitespace-pre-wrap break-words leading-relaxed">
              {data.text}
            </div>
          ) : null}
          {!data.embeddable && data.frame_reason ? (
            <p className="text-[10px] text-corp-muted">
              Live page unavailable here: {data.frame_reason}.
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
