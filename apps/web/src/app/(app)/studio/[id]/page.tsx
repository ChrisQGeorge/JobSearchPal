"use client";

import Link from "next/link";
import { use as usePromise, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { api, apiUrl, ApiError } from "@/lib/api";
import {
  DOC_TYPES,
  type DocType,
  type GeneratedDocument,
} from "@/lib/types";

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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

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
  } | null;
  const isUpload = !!structured?.stored_path;

  return (
    <PageShell
      title={doc.title}
      subtitle={`${doc.doc_type.replace(/_/g, " ")} · v${doc.version}`}
      actions={
        <div className="flex gap-2 items-center">
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
      <Link href="/studio" className="text-sm text-corp-muted hover:text-corp-accent">
        ← Document Studio
      </Link>

      {isUpload && !doc.content_md ? (
        <div className="jsp-card p-5 mt-3 text-sm text-corp-muted">
          This document is an uploaded binary file — there&apos;s no editable
          text body. Use{" "}
          <a
            className="text-corp-accent hover:underline"
            href={apiUrl(`/api/v1/documents/${doc.id}/file`)}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open file
          </a>{" "}
          to view it.
        </div>
      ) : (
        <>
          <div className="jsp-card p-3 mt-3 text-[11px] text-corp-muted flex flex-wrap gap-2 items-center">
            <span>
              Select any span of text to ask the Companion to rewrite it,
              answer a question about it, or spin off a new document.
            </span>
            {saveErr ? (
              <span className="text-corp-danger ml-auto">{saveErr}</span>
            ) : null}
          </div>
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
                // Allow keyboard selection (shift+arrows) to trigger popup too.
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
