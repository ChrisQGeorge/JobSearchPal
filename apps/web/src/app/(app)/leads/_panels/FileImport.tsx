"use client";

// "Import JSON file" for Bright Data sources: upload a snapshot export
// (JSON array or JSON Lines, as downloaded from Bright Data) and run it
// through the same import path as an API snapshot — mapping, the
// source's filters, dedupe, auto-dismiss keyword filters. No Bright Data
// call is made. Large files: upload progress via XHR, then the server
// imports in the background and this polls for progress.

import { useEffect, useRef, useState } from "react";
import { api, apiUrl } from "@/lib/api";

type Progress = {
  status: "importing" | "done" | "failed" | null;
  filename?: string;
  bytes?: number;
  started_at?: string;
  finished_at?: string | null;
  records?: number;
  not_jobs?: number;
  leads?: number;
  auto_dismissed?: number;
  duplicates_or_filtered?: number;
  error?: string | null;
};

const mb = (n: number) => `${(n / (1024 * 1024)).toFixed(n > 100 * 1024 * 1024 ? 0 : 1)} MB`;

function upload(
  url: string,
  file: File,
  onPct: (pct: number) => void,
): Promise<Progress> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onPct(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as Progress);
        return;
      }
      const detail =
        body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : xhr.status === 413
            ? "File too large for the server's upload limit."
            : xhr.responseText.slice(0, 300) || "no detail";
      reject(new Error(`Upload failed (HTTP ${xhr.status}): ${detail}`));
    };
    xhr.onerror = () =>
      reject(new Error("Upload failed: the connection dropped before the server answered."));
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

export function FileImport({
  sourceId,
  onImported,
}: {
  sourceId: number;
  onImported: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [prog, setProg] = useState<Progress | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const endpoint = `/api/v1/job-sources/${sourceId}/import-file`;
  // Latest callback without restarting the poll timer every render.
  const onImportedRef = useRef(onImported);
  onImportedRef.current = onImported;

  // Pick up an import already running (e.g. after a page reload).
  useEffect(() => {
    api
      .get<Progress>(endpoint)
      .then((p) => (p.status === "importing" ? setProg(p) : null))
      .catch(() => {});
  }, [endpoint]);

  // Poll while the server is importing.
  useEffect(() => {
    if (prog?.status !== "importing") return;
    const t = setInterval(async () => {
      try {
        const p = await api.get<Progress>(endpoint);
        setProg(p);
        if (p.status !== "importing") onImportedRef.current();
      } catch {
        /* transient; keep polling */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [prog?.status, endpoint]);

  async function pick(file: File) {
    setErr(null);
    setProg(null);
    setPct(0);
    try {
      const p = await upload(apiUrl(endpoint), file, setPct);
      setProg(p);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPct(null);
      if (input.current) input.current.value = "";
    }
  }

  const busy = pct !== null || prog?.status === "importing";

  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".json,.jsonl,.ndjson,application/json"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void pick(f);
        }}
      />
      <button
        type="button"
        className="jsp-btn-ghost text-xs"
        disabled={busy}
        onClick={() => input.current?.click()}
        title="Import a Bright Data snapshot you downloaded (JSON or JSON Lines). Leads go through the same filters, dedupe and auto-dismiss rules as an API import. No Bright Data call is made."
      >
        {pct !== null ? `Uploading ${pct}%` : prog?.status === "importing" ? "Importing…" : "Import JSON file"}
      </button>
      {prog && prog.status ? (
        <span
          className={`basis-full text-[11px] ${
            prog.status === "failed" ? "text-corp-danger" : "text-corp-accent"
          } whitespace-pre-wrap break-words`}
        >
          {prog.status === "importing" ? "Importing " : prog.status === "done" ? "Imported " : "Import failed — "}
          {prog.filename}
          {prog.bytes ? ` (${mb(prog.bytes)})` : ""}: {prog.records ?? 0} records read ·{" "}
          {prog.leads ?? 0} new leads
          {prog.auto_dismissed ? ` · ${prog.auto_dismissed} auto-dismissed` : ""}
          {prog.duplicates_or_filtered ? ` · ${prog.duplicates_or_filtered} duplicates / filtered out` : ""}
          {prog.not_jobs ? ` · ${prog.not_jobs} non-job / error rows skipped` : ""}
          {prog.error ? `\n${prog.error}` : ""}
          {prog.status !== "importing" ? (
            <button type="button" className="underline ml-2 text-corp-muted" onClick={() => setProg(null)}>
              dismiss
            </button>
          ) : null}
        </span>
      ) : null}
      {err ? (
        <span className="basis-full text-[11px] text-corp-danger whitespace-pre-wrap break-words">
          {err}
          <button type="button" className="underline ml-2 text-corp-muted" onClick={() => setErr(null)}>
            dismiss
          </button>
        </span>
      ) : null}
    </>
  );
}
