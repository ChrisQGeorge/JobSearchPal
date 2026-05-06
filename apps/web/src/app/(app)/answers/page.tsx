"use client";

// Answer bank — the saved-question store the Companion reuses across
// applications. Lifecycle: novel question → ask_user pause on the
// /applications page → user types answer → saved here → next app
// auto-fills.

import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { Paginator, usePagination } from "@/components/Paginator";
import { api, ApiError } from "@/lib/api";

type QuestionAnswer = {
  id: number;
  question_text: string;
  answer: string;
  source: string;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};

export default function AnswersPage() {
  const [items, setItems] = useState<QuestionAnswer[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const pager = usePagination(items, "answers");

  async function refresh() {
    try {
      const rows = await api.get<QuestionAnswer[]>("/api/v1/question-bank");
      setItems(rows);
      setErr(null);
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
  }, []);

  async function remove(id: number) {
    if (!confirm("Delete this saved answer?")) return;
    await api.delete(`/api/v1/question-bank/${id}`);
    await refresh();
  }

  return (
    <PageShell
      title="Answer Bank"
      subtitle="Saved answers the Companion reuses on every application. Built up automatically as you answer novel form questions during application runs."
      actions={
        <div className="flex gap-2">
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={async () => {
              try {
                const res = await api.post<{ inserted: number; skipped: number }>(
                  "/api/v1/question-bank/seed-from-profile",
                );
                alert(
                  `Seed complete — inserted ${res.inserted}, skipped ${res.skipped}.`,
                );
                await refresh();
              } catch (e) {
                alert(
                  e instanceof ApiError
                    ? `Seed failed (HTTP ${e.status}).`
                    : "Seed failed.",
                );
              }
            }}
          >
            Seed from profile
          </button>
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={() => setEditingId("new")}
          >
            + New saved answer
          </button>
        </div>
      }
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger mb-3">{err}</div>
      ) : null}

      {editingId !== null ? (
        <Editor
          item={
            editingId === "new"
              ? null
              : items.find((i) => i.id === editingId) ?? null
          }
          onCancel={() => setEditingId(null)}
          onSaved={async () => {
            setEditingId(null);
            await refresh();
          }}
        />
      ) : null}

      {loading ? (
        <p className="text-corp-muted">Loading…</p>
      ) : items.length === 0 ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          No saved answers yet. They&apos;ll show up here automatically when you
          answer a question during a Companion-driven application run, or you
          can seed one with the <b>+ New saved answer</b> button above.
        </div>
      ) : (
        <div className="jsp-card overflow-hidden">
          <ul className="divide-y divide-corp-border">
            {pager.visibleItems.map((qa) => (
              <li key={qa.id} className="px-4 py-3 hover:bg-corp-surface2">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium">{qa.question_text}</div>
                    <pre className="text-[12px] whitespace-pre-wrap text-corp-muted mt-1 font-sans">
                      {qa.answer}
                    </pre>
                    <div className="text-[10px] text-corp-muted uppercase tracking-wider mt-1">
                      {qa.source}
                      {qa.last_used_at
                        ? ` · last used ${new Date(qa.last_used_at).toLocaleDateString()}`
                        : " · never used"}
                    </div>
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <button
                      className="jsp-btn-ghost text-xs"
                      onClick={() => setEditingId(qa.id)}
                    >
                      Edit
                    </button>
                    <button
                      className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                      onClick={() => remove(qa.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <Paginator
            page={pager.page}
            pageSize={pager.pageSize}
            setPage={pager.setPage}
            setPageSize={pager.setPageSize}
            total={pager.total}
            totalPages={pager.totalPages}
            className="px-4 py-2 border-t border-corp-border"
          />
        </div>
      )}
    </PageShell>
  );
}

function Editor({
  item,
  onCancel,
  onSaved,
}: {
  item: QuestionAnswer | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [question, setQuestion] = useState(item?.question_text ?? "");
  const [answer, setAnswer] = useState(item?.answer ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    if (!question.trim() || !answer.trim()) {
      setErr("Both question and answer are required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await api.put("/api/v1/question-bank", {
        question_text: question.trim(),
        answer: answer.trim(),
        source: item?.source || "manual",
      });
      onSaved();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Save failed (HTTP ${e.status}).`
          : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="jsp-card p-4 mb-3 space-y-3">
      <h3 className="text-sm uppercase tracking-wider text-corp-muted">
        {item ? "Edit saved answer" : "New saved answer"}
      </h3>
      <div>
        <label className="jsp-label">Question</label>
        <input
          className="jsp-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder='e.g. "Are you authorized to work in the United States?"'
          disabled={saving}
        />
      </div>
      <div>
        <label className="jsp-label">Answer</label>
        <textarea
          className="jsp-input min-h-[100px] text-sm"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Your standard answer."
          disabled={saving}
        />
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="jsp-btn-primary"
          onClick={save}
          disabled={saving || !question.trim() || !answer.trim()}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
