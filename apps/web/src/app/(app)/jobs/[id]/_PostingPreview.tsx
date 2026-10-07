"use client";

// Posting preview on the job detail page. Loads automatically when the
// page opens: the server fetches the apply link (most job boards refuse
// to be framed, so a bare <iframe> would usually be blank), finds the
// work-arrangement wording, and returns a readable copy. When the site
// does allow framing, the live page can be shown too.

import { useEffect, useState } from "react";
import { api, apiUrl, ApiError } from "@/lib/api";

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
  // page  = rendered snapshot served by our API (works for boards that
  //         refuse framing, e.g. LinkedIn) — the default
  // live  = the real site in an iframe (only when the site allows it)
  // text  = readable copy
  const [view, setView] = useState<"page" | "live" | "text">("page");
  // Bumped on Refresh so the snapshot iframe reloads.
  const [snapVer, setSnapVer] = useState(0);
  // Hidden = nothing is fetched or framed. Remembered across every job
  // page (one localStorage key). null until read, so a hidden preference
  // never triggers a load on the first render.
  const [collapsed, setCollapsed] = useState<boolean | null>(null);

  useEffect(() => {
    let hidden = false;
    try {
      hidden = localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      /* storage blocked — default to shown */
    }
    setCollapsed(hidden);
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
      if (refresh) setSnapVer((v) => v + 1);
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

  // New job → drop the previous job's preview.
  useEffect(() => {
    setData(null);
    setErr(null);
  }, [jobId, sourceUrl]);

  // Load only while shown (and only once per job until Refresh).
  useEffect(() => {
    if (collapsed !== false || data || loading || err) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collapsed, jobId, sourceUrl, data, err]);

  if (!sourceUrl) return null;

  function toggle() {
    const next = !collapsed;
    try {
      localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
    } catch {
      /* ignore */
    }
    setCollapsed(next);
  }

  const guess = data?.arrangement.guess ?? null;
  const listed = (remotePolicy ?? "").toLowerCase() || null;
  const mismatch =
    guess && guess !== "mixed" && listed && listed !== guess ? guess : null;

  return (
    <section className="jsp-card p-3 mb-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Posting</span>
        <button
          type="button"
          onClick={toggle}
          className="jsp-btn-ghost text-[11px] py-0.5"
          title="Hidden: the posting isn't fetched or shown. Remembered on every job page."
        >
          {collapsed ? "Show posting" : "Hide posting"}
        </button>
        {collapsed ? (
          <span className="text-[11px] text-corp-muted">hidden — not loaded</span>
        ) : loading ? (
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
        {!collapsed && mismatch ? (
          <span className="text-[11px] text-corp-danger">
            Job is saved as <b>{listed}</b>
          </span>
        ) : null}
        {!collapsed && data && guess === "mixed" ? (
          <span className="text-[11px] text-corp-muted">set it yourself:</span>
        ) : null}
        {!collapsed && data && (mismatch || guess === "mixed")
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
          {!collapsed && data ? (
            <span className="flex rounded border border-corp-border overflow-hidden text-[11px]">
              {(data.embeddable ? (["page", "live", "text"] as const) : (["page", "text"] as const)).map(
                (v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setView(v)}
                    title={
                      v === "page"
                        ? "The page as the site renders it (a sandboxed copy fetched by the server)"
                        : v === "live"
                          ? "The real site, embedded"
                          : "Readable text only"
                    }
                    className={`px-2 py-0.5 ${view === v ? "bg-corp-accent/20 text-corp-accent" : "text-corp-muted"}`}
                  >
                    {v === "page" ? "Page" : v === "live" ? "Live site" : "Text"}
                  </button>
                ),
              )}
            </span>
          ) : null}
          {!collapsed ? (
            <button
              type="button"
              className="jsp-btn-ghost text-[11px] py-0.5"
              onClick={() => void load(true)}
              disabled={loading}
              title="Fetch the posting again"
            >
              Refresh
            </button>
          ) : null}
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

      {err && !collapsed ? (
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
              The site returned almost no readable text — it builds the page with JavaScript or
              blocks automated viewers, so the Page view may be incomplete
              {data.embeddable ? "; try Live site" : "; use “Open ↗”"}.
            </p>
          ) : null}
          {view === "page" ? (
            // Our own endpoint, but the HTML inside is the job site's: no
            // allow-same-origin, so its scripts run in an opaque origin and
            // can't use the session or reach the app (the response also
            // carries a CSP sandbox header).
            <iframe
              key={`snap-${jobId}-${snapVer}`}
              src={apiUrl(`/api/v1/jobs/${jobId}/posting-snapshot?v=${snapVer}`)}
              className="w-full h-[75vh] rounded border border-corp-border bg-white"
              sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox allow-forms"
              referrerPolicy="no-referrer"
              title="Job posting (rendered copy)"
            />
          ) : view === "live" && data.embeddable ? (
            <iframe
              src={data.final_url}
              className="w-full h-[75vh] rounded border border-corp-border bg-white"
              sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
              referrerPolicy="no-referrer"
              title="Job posting"
            />
          ) : data.text.trim() ? (
            <div className="max-h-[50vh] overflow-y-auto rounded border border-corp-border p-3 text-xs whitespace-pre-wrap break-words leading-relaxed">
              {data.text}
            </div>
          ) : null}
          {view === "page" ? (
            <p className="text-[10px] text-corp-muted">
              Rendered copy of the page as the site served it to the server (interactive bits that
              need a login or the site's own scripts may not work — use “Open ↗” for those).
              {!data.embeddable && data.frame_reason ? ` The live site can't be embedded: ${data.frame_reason}.` : ""}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
