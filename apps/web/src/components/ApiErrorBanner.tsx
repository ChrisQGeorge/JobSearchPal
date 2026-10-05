"use client";

// App-wide banner for server-side failures. lib/api.ts fires
// API_ERROR_EVENT on any 5xx / unreachable response with the structured
// error block (code, message, hint, request id); this shows the latest
// one so a failure is never just a bare "HTTP 500".

import { useEffect, useState } from "react";
import { API_ERROR_EVENT, type ApiErrorInfo } from "@/lib/api";

type Shown = ApiErrorInfo & { status: number; at: number; count: number };

export function ApiErrorBanner() {
  const [err, setErr] = useState<Shown | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onErr(e: Event) {
      const d = (e as CustomEvent).detail as ApiErrorInfo & { status: number };
      setErr((prev) =>
        prev && prev.code === d.code && Date.now() - prev.at < 60000
          ? { ...prev, ...d, at: Date.now(), count: prev.count + 1 }
          : { ...d, at: Date.now(), count: 1 },
      );
    }
    window.addEventListener(API_ERROR_EVENT, onErr);
    return () => window.removeEventListener(API_ERROR_EVENT, onErr);
  }, []);

  if (!err) return null;
  return (
    <div className="fixed bottom-3 left-3 right-3 md:left-auto md:w-[30rem] z-50 rounded-lg border border-corp-danger/50 bg-corp-surface shadow-lg p-3 text-xs space-y-1">
      <div className="flex items-start gap-2">
        <span className="font-mono font-semibold text-corp-danger">{err.code}</span>
        {err.count > 1 ? (
          <span className="text-corp-muted">×{err.count}</span>
        ) : null}
        <button
          type="button"
          className="ml-auto text-corp-muted hover:text-corp-text"
          onClick={() => setErr(null)}
          aria-label="Dismiss error"
        >
          ✕
        </button>
      </div>
      <p className="text-corp-text">{err.message}</p>
      {err.hint ? <p className="text-corp-muted">{err.hint}</p> : null}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-corp-muted">
        {err.path ? <span className="font-mono">{err.path}</span> : null}
        {err.request_id ? (
          <span title="Search the API log for this id: docker logs jsp-api | grep <id>">
            request <span className="font-mono">{err.request_id}</span>
          </span>
        ) : null}
        <span>{err.status ? `HTTP ${err.status}` : "no response"}</span>
        <a href="/health/deep" target="_blank" rel="noopener noreferrer" className="text-corp-accent hover:underline">
          diagnostics
        </a>
        <button type="button" className="text-corp-accent hover:underline" onClick={() => setOpen((o) => !o)}>
          {open ? "less" : "copy details"}
        </button>
      </div>
      {open ? (
        <textarea
          readOnly
          className="w-full h-24 font-mono text-[10px] rounded border border-corp-border bg-corp-surface2 p-1"
          value={JSON.stringify(err, null, 2)}
          onFocus={(e) => e.currentTarget.select()}
        />
      ) : null}
    </div>
  );
}
