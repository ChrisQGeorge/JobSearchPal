"use client";

import Link from "next/link";
import { use as usePromise, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageShell } from "@/components/PageShell";
import { api, apiUrl, ApiError } from "@/lib/api";
import {
  DOC_TYPES,
  type DocType,
  type GeneratedDocument,
} from "@/lib/types";

type ViewMode = "edit" | "preview";

const PREVIEWABLE_DOC_TYPES: ReadonlySet<string> = new Set([
  "resume",
  "cover_letter",
  "outreach_email",
  "thank_you",
  "followup",
  "portfolio",
  "reference",
  "other",
]);

// Doc-type → the human-readable token we drop into the filename. Defaults
// to Title-Case of the raw type with underscores replaced by hyphens.
const DOC_TYPE_FILENAME: Record<string, string> = {
  resume: "Resume",
  cover_letter: "Cover-Letter",
  outreach_email: "Outreach",
  thank_you: "Thank-You",
  followup: "Followup",
  portfolio: "Portfolio",
  reference: "Reference",
  offer_letter: "Offer-Letter",
  transcript: "Transcript",
  certificate: "Certificate",
  other: "Doc",
};

/** Sanitize any stray token for safe use in a filename. Replaces runs of
 * whitespace with a single hyphen, drops characters that cause trouble
 * on Windows / macOS / Linux, and collapses consecutive hyphens. */
function _fnToken(raw: string | null | undefined): string {
  if (!raw) return "";
  return raw
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function buildFilenameBase(params: {
  name: string | null;
  docType: string;
  orgName: string | null;
  fallbackTitle: string;
}): string {
  const nameTok = _fnToken(params.name);
  const typeTok = _fnToken(
    DOC_TYPE_FILENAME[params.docType] ?? params.docType,
  );
  const orgTok = _fnToken(params.orgName);
  const pieces = [nameTok, typeTok, orgTok].filter(Boolean);
  if (pieces.length >= 2) return pieces.join("_");
  // Fallback when we're missing the name / org — use the doc's title as a
  // last resort so the file still gets a sensible name.
  const fallback = _fnToken(params.fallbackTitle) || "Document";
  return pieces.length === 0 ? fallback : `${pieces[0]}_${fallback}`;
}

function downloadMarkdown(filenameBase: string, content: string): void {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filenameBase}.md`;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Give the browser a tick to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function printWithFilename(filenameBase: string): void {
  // Browsers derive the "Save as PDF" filename suggestion from document.title.
  // Swap it in just around the print dialog so the real app title comes back
  // after the print spooler finishes (the afterprint event is reliable in
  // Chrome / Firefox / Safari).
  const originalTitle = document.title;
  const onAfter = () => {
    document.title = originalTitle;
    window.removeEventListener("afterprint", onAfter);
  };
  window.addEventListener("afterprint", onAfter);
  document.title = filenameBase;
  window.print();
}

type SelectionEditMode = "rewrite" | "answer" | "new_document";

type SelectionEditResult = {
  mode: SelectionEditMode;
  replacement_text?: string | null;
  answer_text?: string | null;
  document?: GeneratedDocument | null;
  notes?: string | null;
  warning?: string | null;
};

type PopupState = {
  // Start / end offsets in the textarea value.
  start: number;
  end: number;
  // Absolute client position to anchor the popup (relative to viewport).
  x: number;
  y: number;
  selectionText: string;
};

export default function DocumentEditorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = usePromise(params);
  const docId = Number(id);
  const router = useRouter();

  const [doc, setDoc] = useState<GeneratedDocument | null>(null);
  const [body, setBody] = useState<string>("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [popup, setPopup] = useState<PopupState | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [parentDoc, setParentDoc] = useState<GeneratedDocument | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("preview");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // Data fetched lazily for the download-filename feature. We need:
  //  - the user's full name (from Resume Profile, auth, or demographics)
  //  - the owning TrackedJob's organization name, if any
  // so we can compose a filename like "Christopher-George_Resume_Amazon".
  const [profileName, setProfileName] = useState<string | null>(null);
  const [orgName, setOrgName] = useState<string | null>(null);

  // Fetch the user's canonical name + the owning job's org so we can build
  // a nice download filename (`Firstname-Lastname_Resume_Acme.pdf`). Both
  // lookups fail silently — we just fall back to the doc title.
  useEffect(() => {
    let cancelled = false;
    api
      .get<{
        full_name?: string | null;
      } | null>("/api/v1/preferences/resume-profile")
      .then((p) => {
        if (cancelled) return;
        setProfileName((p?.full_name || "").trim() || null);
      })
      .catch(() => {
        /* non-fatal */
      });
    api
      .get<{ display_name?: string | null; email?: string | null } | null>(
        "/api/v1/auth/me",
      )
      .then((u) => {
        if (cancelled) return;
        // Only use auth name if Resume Profile didn't answer first.
        setProfileName((prev) => prev ?? ((u?.display_name || "").trim() || null));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!doc?.tracked_job_id) {
      setOrgName(null);
      return;
    }
    let cancelled = false;
    api
      .get<{ organization_id: number | null }>(
        `/api/v1/jobs/${doc.tracked_job_id}`,
      )
      .then(async (job) => {
        if (cancelled || !job.organization_id) return;
        const org = await api.get<{ name: string }>(
          `/api/v1/organizations/${job.organization_id}`,
        );
        if (!cancelled) setOrgName((org?.name || "").trim() || null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [doc?.tracked_job_id]);

  // Load the parent doc lazily when the user wants the diff view.
  useEffect(() => {
    if (!showDiff || !doc?.parent_version_id) return;
    let cancelled = false;
    api
      .get<GeneratedDocument>(`/api/v1/documents/${doc.parent_version_id}`)
      .then((p) => {
        if (!cancelled) setParentDoc(p);
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, [showDiff, doc?.parent_version_id]);

  async function load() {
    try {
      const d = await api.get<GeneratedDocument>(`/api/v1/documents/${docId}`);
      setDoc(d);
      setBody(d.content_md ?? "");
      setDirty(false);
      setLoadErr(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setLoadErr("Document not found.");
      } else {
        setLoadErr("Failed to load document.");
      }
    }
  }

  useEffect(() => {
    if (!Number.isFinite(docId)) {
      setLoadErr("Invalid document id.");
      return;
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId]);

  // While the doc is still being generated in the background (async tailor),
  // poll every 2s until it's ready or errors. Stop polling the moment the
  // user starts editing (`dirty`) so we don't clobber local changes.
  useEffect(() => {
    const status = (doc?.content_structured as { status?: string } | null)
      ?.status;
    if (status !== "generating") return;
    if (dirty) return;
    const handle = setInterval(() => {
      load();
    }, 2000);
    return () => clearInterval(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.content_structured, dirty]);

  async function save() {
    if (!doc) return;
    setSaving(true);
    setSaveErr(null);
    try {
      const updated = await api.put<GeneratedDocument>(
        `/api/v1/documents/${doc.id}`,
        { content_md: body, title: doc.title },
      );
      setDoc(updated);
      setBody(updated.content_md ?? "");
      setDirty(false);
    } catch (e) {
      setSaveErr(
        e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!doc) return;
    if (!confirm("Delete this document?")) return;
    await api.delete(`/api/v1/documents/${doc.id}`);
    router.replace("/studio");
  }

  function onSelectionEnd() {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    if (start === end) {
      setPopup(null);
      return;
    }
    const selectionText = ta.value.slice(start, end);
    if (!selectionText.trim()) {
      setPopup(null);
      return;
    }
    // Anchor the popup near the end of the selection (textarea can't give us
    // per-character coords, so approximate with the textarea's bounding rect).
    const rect = ta.getBoundingClientRect();
    setPopup({
      start,
      end,
      x: rect.left + rect.width / 2,
      y: rect.top + 12,
      selectionText,
    });
  }

  function applyReplacement(replacement: string) {
    if (!popup) return;
    const next = body.slice(0, popup.start) + replacement + body.slice(popup.end);
    setBody(next);
    setDirty(true);
    setPopup(null);
    // Move cursor to end of replacement after state settles.
    requestAnimationFrame(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      const newPos = popup.start + replacement.length;
      ta.focus();
      ta.setSelectionRange(newPos, newPos);
    });
  }

  if (loadErr) {
    return (
      <PageShell title="Document Editor">
        <div className="jsp-card p-6 text-sm text-corp-danger">{loadErr}</div>
        <Link href="/studio" className="jsp-btn-ghost inline-block mt-4">
          ← Back to Document Studio
        </Link>
      </PageShell>
    );
  }
  if (!doc) {
    return (
      <PageShell title="Document Editor">
        <p className="text-corp-muted">Loading...</p>
      </PageShell>
    );
  }

  const structured = (doc.content_structured ?? null) as {
    original_filename?: string | null;
    stored_path?: string | null;
    mime_type?: string | null;
    extracted_from?: string | null;
    status?: "generating" | "ready" | "error" | null;
    notes?: string | null;
    warning?: string | null;
    error?: string | null;
    started_at?: string | null;
  } | null;
  const isUpload = !!structured?.stored_path;
  const genStatus = structured?.status ?? null;
  const isGenerating = genStatus === "generating";
  const genError = genStatus === "error" ? structured?.error ?? null : null;
  const extractedFrom = structured?.extracted_from ?? null;
  const isExtracted =
    isUpload && extractedFrom && extractedFrom !== "text";

  // Build the download filename: `Firstname-Lastname_Resume_Acme`. Every
  // component is sanitized (space → hyphen, non-safe chars dropped) and
  // missing components collapse to a shorter name. Used for both .md
  // download and the PDF print dialog's proposed filename.
  const filenameBase = buildFilenameBase({
    name: profileName,
    docType: doc.doc_type,
    orgName,
    fallbackTitle: doc.title,
  });
  const canPreview =
    !isUpload && !!body && PREVIEWABLE_DOC_TYPES.has(doc.doc_type);
  const effectiveMode: ViewMode = canPreview ? viewMode : "edit";

  return (
    <PageShell
      title={doc.title}
      subtitle={`${doc.doc_type.replace(/_/g, " ")} · v${doc.version}`}
      actions={
        <div className="flex gap-2 items-center flex-wrap jsp-no-print">
          {doc.tracked_job_id ? (
            <Link
              href={`/jobs/${doc.tracked_job_id}`}
              className="jsp-btn-ghost text-xs"
            >
              → Job
            </Link>
          ) : null}
          {isUpload ? (
            <a
              className="jsp-btn-ghost text-xs"
              href={apiUrl(`/api/v1/documents/${doc.id}/file`)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open file
            </a>
          ) : null}
          {canPreview ? (
            <div
              className="inline-flex rounded-md border border-corp-border overflow-hidden text-xs"
              role="tablist"
              aria-label="View mode"
            >
              <button
                type="button"
                role="tab"
                aria-selected={effectiveMode === "preview"}
                className={`px-2.5 py-1 ${
                  effectiveMode === "preview"
                    ? "bg-corp-accent text-corp-bg"
                    : "bg-corp-surface text-corp-text hover:bg-corp-surface2"
                }`}
                onClick={() => setViewMode("preview")}
              >
                Preview
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={effectiveMode === "edit"}
                className={`px-2.5 py-1 border-l border-corp-border ${
                  effectiveMode === "edit"
                    ? "bg-corp-accent text-corp-bg"
                    : "bg-corp-surface text-corp-text hover:bg-corp-surface2"
                }`}
                onClick={() => setViewMode("edit")}
              >
                Edit
              </button>
            </div>
          ) : null}
          {canPreview ? (
            <button
              type="button"
              className="jsp-btn-ghost text-xs"
              onClick={() => printWithFilename(filenameBase)}
              title={`Open the browser print dialog — proposes "${filenameBase}.pdf"`}
            >
              Print / PDF
            </button>
          ) : null}
          {doc.content_md && !isUpload ? (
            <button
              type="button"
              className="jsp-btn-ghost text-xs"
              onClick={() => downloadMarkdown(filenameBase, body)}
              title={`Download "${filenameBase}.md"`}
            >
              Download .md
            </button>
          ) : null}
          {doc.content_md && !isUpload ? (
            <HumanizeButton
              docId={doc.id}
              onCreated={(newId) => router.push(`/studio/${newId}`)}
            />
          ) : null}
          {doc.parent_version_id ? (
            <button
              className="jsp-btn-ghost text-xs"
              onClick={() => setShowDiff((v) => !v)}
              title="Compare against the previous version"
            >
              {showDiff ? "Hide diff" : `Diff vs v${doc.version - 1}`}
            </button>
          ) : null}
          <button
            className="jsp-btn-primary"
            onClick={save}
            disabled={saving || !dirty}
          >
            {saving ? "Saving..." : dirty ? "Save" : "Saved"}
          </button>
          <button
            className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
            onClick={remove}
          >
            Delete
          </button>
        </div>
      }
    >
      <Link
        href="/studio"
        className="text-sm text-corp-muted hover:text-corp-accent jsp-no-print"
      >
        ← Document Studio
      </Link>

      {isGenerating ? (
        <div className="jsp-card p-5 mt-3 text-sm">
          <div className="flex items-center gap-3">
            <span
              className="inline-block w-3 h-3 rounded-full bg-corp-accent animate-pulse"
              aria-hidden
            />
            <span className="text-corp-text font-medium">
              Generating — the Companion is drafting this document.
            </span>
          </div>
          <p className="text-corp-muted mt-2">
            Checking every 2 seconds. This typically takes under a minute but
            can run up to ~10 minutes if Claude is rate-limited. You can leave
            this page and come back; the document will be waiting for you.
          </p>
        </div>
      ) : genError ? (
        <div className="jsp-card p-5 mt-3 text-sm border-corp-danger/40">
          <div className="text-corp-danger font-medium">
            Generation failed.
          </div>
          <p className="text-corp-muted mt-2 whitespace-pre-wrap">{genError}</p>
          <p className="text-corp-muted mt-2">
            Re-run the tailor from the job page to try again.
          </p>
        </div>
      ) : isUpload && !doc.content_md ? (
        <div className="jsp-card p-5 mt-3 text-sm text-corp-muted">
          No readable text body — we couldn&apos;t extract anything from this
          file. Use{" "}
          <a
            className="text-corp-accent hover:underline"
            href={apiUrl(`/api/v1/documents/${doc.id}/file`)}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open file
          </a>{" "}
          to view the original.
        </div>
      ) : (
        <>
          <div className="jsp-card p-3 mt-3 text-[11px] text-corp-muted flex flex-wrap gap-2 items-center jsp-no-print">
            {effectiveMode === "edit" ? (
              <span>
                Select any span of text to ask the Companion to rewrite it,
                answer a question about it, or spin off a new document.
              </span>
            ) : (
              <span>
                Preview mode — what the document looks like formatted. Use
                Print / PDF to export, or switch to Edit to tweak the markdown.
              </span>
            )}
            {isExtracted ? (
              <span className="text-corp-accent2">
                · Extracted from {extractedFrom?.toUpperCase()}. Edits save to the
                text version; the original {extractedFrom} is still available
                via Open file.
              </span>
            ) : null}
            {saveErr ? (
              <span className="text-corp-danger ml-auto">{saveErr}</span>
            ) : null}
          </div>
          {showDiff && parentDoc ? (
            <DiffPanel
              previous={parentDoc.content_md ?? ""}
              current={body}
              previousVersion={parentDoc.version}
              currentVersion={doc.version}
            />
          ) : null}
          {effectiveMode === "preview" ? (
            <div className="jsp-print-root mt-3">
              <article className="jsp-document jsp-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {body}
                </ReactMarkdown>
              </article>
            </div>
          ) : (
            <div className="jsp-card p-0 mt-2 relative">
              <textarea
                ref={textareaRef}
                className="w-full min-h-[70vh] bg-corp-surface text-sm font-mono p-4 border-0 focus:outline-none resize-y"
                value={body}
                onChange={(e) => {
                  setBody(e.target.value);
                  setDirty(true);
                  if (popup) setPopup(null);
                }}
                onMouseUp={onSelectionEnd}
                onKeyUp={(e) => {
                  if (
                    e.key === "Shift" ||
                    e.key === "ArrowLeft" ||
                    e.key === "ArrowRight" ||
                    e.key === "ArrowUp" ||
                    e.key === "ArrowDown"
                  ) {
                    onSelectionEnd();
                  }
                }}
              />
            </div>
          )}
        </>
      )}

      {popup ? (
        <SelectionPopup
          docId={doc.id}
          popup={popup}
          onClose={() => setPopup(null)}
          onReplacement={applyReplacement}
        />
      ) : null}
    </PageShell>
  );
}

function SelectionPopup({
  docId,
  popup,
  onClose,
  onReplacement,
}: {
  docId: number;
  popup: PopupState;
  onClose: () => void;
  onReplacement: (replacement: string) => void;
}) {
  const [mode, setMode] = useState<SelectionEditMode>("rewrite");
  const [instruction, setInstruction] = useState("");
  const [newDocType, setNewDocType] = useState<DocType>("other");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SelectionEditResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    if (!instruction.trim()) {
      setErr("Add an instruction first.");
      return;
    }
    setRunning(true);
    setErr(null);
    setResult(null);
    try {
      const res = await api.post<SelectionEditResult>(
        `/api/v1/documents/${docId}/selection-edit`,
        {
          mode,
          selection_text: popup.selectionText,
          selection_start: popup.start,
          selection_end: popup.end,
          instruction: instruction.trim(),
          new_doc_type: mode === "new_document" ? newDocType : null,
        },
      );
      setResult(res);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Request failed (HTTP ${e.status}).` : "Request failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  // Anchor the popup as a fixed-position card near the selection.
  return (
    <>
      <button
        type="button"
        aria-label="Close selection popup"
        className="fixed inset-0 z-30 bg-black/40"
        onClick={onClose}
      />
      <div
        className="fixed z-40 jsp-card p-4 shadow-xl w-[min(560px,92vw)]"
        style={{
          left: `min(max(12px, ${popup.x}px - 280px), calc(100vw - 572px))`,
          top: `min(max(80px, ${popup.y}px), calc(100vh - 200px))`,
        }}
      >
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="text-xs uppercase tracking-wider text-corp-muted">
            Selection · {popup.end - popup.start} chars
          </div>
          <button className="jsp-btn-ghost text-xs" onClick={onClose}>
            Close
          </button>
        </div>

        <blockquote className="text-xs bg-corp-surface2 border border-corp-border rounded p-2 max-h-32 overflow-auto whitespace-pre-wrap">
          {popup.selectionText}
        </blockquote>

        <div className="flex flex-wrap gap-1 mt-3">
          <ModeButton
            active={mode === "rewrite"}
            onClick={() => setMode("rewrite")}
            label="Rewrite selection"
          />
          <ModeButton
            active={mode === "answer"}
            onClick={() => setMode("answer")}
            label="Answer a question"
          />
          <ModeButton
            active={mode === "new_document"}
            onClick={() => setMode("new_document")}
            label="Create new document"
          />
        </div>

        {mode === "new_document" ? (
          <div className="mt-2">
            <label className="jsp-label">New document type</label>
            <select
              className="jsp-input"
              value={newDocType}
              onChange={(e) => setNewDocType(e.target.value as DocType)}
              disabled={running}
            >
              {DOC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        <div className="mt-2">
          <label className="jsp-label">
            {mode === "rewrite"
              ? "How should this be rewritten?"
              : mode === "answer"
                ? "What do you want to know about this?"
                : "Describe the new document you want"}
          </label>
          <textarea
            className="jsp-input min-h-[80px]"
            placeholder={
              mode === "rewrite"
                ? "Make it more concrete. Drop the adjectives. Shorten by half."
                : mode === "answer"
                  ? "Why might this sound weak to a hiring manager?"
                  : "Draft a cover letter opening based on this bullet."
            }
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            disabled={running}
          />
        </div>

        {err ? <div className="text-xs text-corp-danger mt-2">{err}</div> : null}

        <div className="flex justify-end gap-2 mt-3">
          <button
            className="jsp-btn-ghost"
            onClick={onClose}
            disabled={running}
            type="button"
          >
            Cancel
          </button>
          <button
            className="jsp-btn-primary"
            onClick={run}
            disabled={running || !instruction.trim()}
            type="button"
          >
            {running
              ? mode === "rewrite"
                ? "Rewriting..."
                : mode === "answer"
                  ? "Thinking..."
                  : "Writing..."
              : "Run"}
          </button>
        </div>

        {result ? (
          <div className="mt-3 border-t border-corp-border pt-3 space-y-2">
            {result.warning ? (
              <div className="text-xs text-corp-accent2 bg-corp-accent2/10 border border-corp-accent2/40 p-2 rounded">
                ⚠ {result.warning}
              </div>
            ) : null}
            {result.notes ? (
              <div className="text-[11px] text-corp-muted italic">
                Companion: {result.notes}
              </div>
            ) : null}

            {result.mode === "rewrite" && result.replacement_text ? (
              <div className="space-y-2">
                <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                  Proposed replacement
                </div>
                <pre className="text-sm whitespace-pre-wrap font-mono bg-corp-surface2 border border-corp-border p-3 rounded max-h-64 overflow-auto">
                  {result.replacement_text}
                </pre>
                <div className="flex justify-end gap-2">
                  <button
                    className="jsp-btn-ghost"
                    onClick={() => setResult(null)}
                    type="button"
                  >
                    Discard
                  </button>
                  <button
                    className="jsp-btn-primary"
                    onClick={() =>
                      result.replacement_text &&
                      onReplacement(result.replacement_text)
                    }
                    type="button"
                  >
                    Accept replacement
                  </button>
                </div>
              </div>
            ) : null}

            {result.mode === "answer" && result.answer_text ? (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
                  Answer
                </div>
                <p className="text-sm whitespace-pre-wrap">{result.answer_text}</p>
              </div>
            ) : null}

            {result.mode === "new_document" && result.document ? (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
                  New document created
                </div>
                <p className="text-sm">
                  <Link
                    href={`/studio/${result.document.id}`}
                    className="text-corp-accent hover:underline"
                  >
                    → Open {result.document.title}
                  </Link>
                </p>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}

function ModeButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-2.5 py-1 rounded-md text-xs border transition-colors ${
        active
          ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
          : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text"
      }`}
    >
      {label}
    </button>
  );
}

function HumanizeButton({
  docId,
  onCreated,
}: {
  docId: number;
  onCreated: (newId: number) => void;
}) {
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setErr(null);
    try {
      const created = await api.post<GeneratedDocument>(
        `/api/v1/documents/${docId}/humanize`,
        { max_samples: 5 },
      );
      onCreated(created.id);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Humanize failed (HTTP ${e.status}).`
          : "Humanize failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        className="jsp-btn-ghost text-xs"
        onClick={run}
        disabled={running}
        title="Rewrite this document in your voice using your Writing Samples"
      >
        {running ? "Humanizing..." : "Humanize"}
      </button>
      {err ? (
        <span className="text-[10px] text-corp-danger mt-0.5">{err}</span>
      ) : null}
    </div>
  );
}

// Minimal line-based diff — good enough for markdown documents where
// paragraphs are naturally line-separated. Myers' algorithm is overkill for
// the short documents we ship; a longest-common-subsequence on lines is fine.
function diffLines(prev: string, curr: string): Array<
  { type: "same" | "add" | "remove"; text: string }
> {
  const a = prev.split("\n");
  const b = curr.split("\n");
  // LCS DP table.
  const m = a.length;
  const n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    new Array(n + 1).fill(0),
  );
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (a[i] === b[j]) dp[i][j] = dp[i + 1][j + 1] + 1;
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: Array<{ type: "same" | "add" | "remove"; text: string }> = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      out.push({ type: "same", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: "remove", text: a[i] });
      i++;
    } else {
      out.push({ type: "add", text: b[j] });
      j++;
    }
  }
  while (i < m) {
    out.push({ type: "remove", text: a[i++] });
  }
  while (j < n) {
    out.push({ type: "add", text: b[j++] });
  }
  return out;
}

function DiffPanel({
  previous,
  current,
  previousVersion,
  currentVersion,
}: {
  previous: string;
  current: string;
  previousVersion: number;
  currentVersion: number;
}) {
  const diff = diffLines(previous, current);
  const added = diff.filter((d) => d.type === "add").length;
  const removed = diff.filter((d) => d.type === "remove").length;

  return (
    <div className="jsp-card p-0 mt-2 overflow-hidden">
      <div className="px-3 py-2 text-[11px] text-corp-muted border-b border-corp-border flex items-center justify-between">
        <span>
          Diff · v{previousVersion} → v{currentVersion}
        </span>
        <span>
          <span className="text-emerald-300">+{added}</span>{" "}
          <span className="text-corp-danger">-{removed}</span>
        </span>
      </div>
      <pre className="font-mono text-xs leading-relaxed max-h-[60vh] overflow-auto">
        {diff.map((d, i) => {
          if (d.type === "same") {
            if (d.text === "" && i !== 0 && i !== diff.length - 1)
              return <div key={i} className="px-3">&nbsp;</div>;
            return (
              <div key={i} className="px-3 text-corp-muted">
                {d.text || "\u00a0"}
              </div>
            );
          }
          if (d.type === "add") {
            return (
              <div
                key={i}
                className="px-3 bg-emerald-500/10 text-emerald-300"
              >
                <span className="inline-block w-3 text-emerald-400">+</span>
                {d.text || "\u00a0"}
              </div>
            );
          }
          return (
            <div key={i} className="px-3 bg-corp-danger/10 text-corp-danger">
              <span className="inline-block w-3 text-corp-danger">-</span>
              {d.text || "\u00a0"}
            </div>
          );
        })}
      </pre>
    </div>
  );
}
