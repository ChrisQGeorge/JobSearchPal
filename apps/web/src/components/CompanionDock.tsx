"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, ApiError } from "@/lib/api";
import type {
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
} from "@/lib/types";

// LocalStorage key so the user's minimized/expanded choice survives reloads.
const LS_OPEN_KEY = "jsp.companionDock.open";
const LS_ACTIVE_KEY = "jsp.companionDock.activeId";

// Routes we don't render the dock on — the /companion page has its own
// full-screen chat. Auth screens shouldn't show it either.
const HIDDEN_PATHS = new Set<string>(["/login", "/companion"]);

type DockAttachedDoc = {
  id: number;
  title: string;
  filename: string | null;
  size_bytes: number | null;
  has_inline_text: boolean;
};

export function CompanionDock() {
  const pathname = usePathname() ?? "/";
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [attachments, setAttachments] = useState<DockAttachedDoc[]>([]);
  const [attaching, setAttaching] = useState(false);
  const attachRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Read persisted UI state.
  useEffect(() => {
    if (typeof window === "undefined") return;
    setOpen(window.localStorage.getItem(LS_OPEN_KEY) === "1");
    const aid = window.localStorage.getItem(LS_ACTIVE_KEY);
    if (aid) {
      const n = Number(aid);
      if (Number.isFinite(n)) setActiveId(n);
    }
  }, []);

  // Probe auth — the dock is cookie-bearer auth only. If unauthenticated, hide.
  useEffect(() => {
    let cancelled = false;
    api
      .get("/api/v1/auth/me")
      .then(() => {
        if (!cancelled) setAuthed(true);
      })
      .catch(() => {
        if (!cancelled) setAuthed(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  // Load the conversation list once authed AND the user opens the dock for the
  // first time. Saves a round-trip on pages where the user never opens it.
  const loadList = useCallback(async () => {
    try {
      const data = await api.get<ConversationSummary[]>(
        "/api/v1/companion/conversations",
      );
      setConversations(data);
      // Prefer saved activeId; fall back to most-recent.
      setActiveId((prev) => {
        if (prev && data.some((c) => c.id === prev)) return prev;
        return data[0]?.id ?? null;
      });
    } catch {
      /* non-fatal */
    }
  }, []);

  useEffect(() => {
    if (authed && open) loadList();
  }, [authed, open, loadList]);

  // Load the full detail of the active conversation.
  useEffect(() => {
    if (!open || !activeId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetail(null);
    api
      .get<ConversationDetail>(`/api/v1/companion/conversations/${activeId}`)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, open]);

  // Auto-scroll to bottom as messages arrive.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [detail?.messages.length, sending]);

  function persistOpen(next: boolean) {
    setOpen(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LS_OPEN_KEY, next ? "1" : "0");
    }
  }

  function selectConversation(id: number) {
    setActiveId(id);
    setSwitcherOpen(false);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LS_ACTIVE_KEY, String(id));
    }
  }

  async function createAndFocus() {
    try {
      const c = await api.post<ConversationSummary>(
        "/api/v1/companion/conversations",
        { title: null },
      );
      setConversations((prev) => [c, ...prev]);
      selectConversation(c.id);
    } catch {
      /* non-fatal */
    }
  }

  async function attachFile(file: File) {
    setAttaching(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("doc_type", "other");
      const res = await fetch(apiUrl("/api/v1/documents/upload"), {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status}: ${txt.slice(0, 200)}`);
      }
      const doc = (await res.json()) as {
        id: number;
        title: string;
        content_structured?: {
          original_filename?: string | null;
          size_bytes?: number | null;
          has_inline_text?: boolean | null;
        } | null;
      };
      const s = doc.content_structured ?? null;
      setAttachments((prev) => [
        ...prev,
        {
          id: doc.id,
          title: doc.title,
          filename: s?.original_filename ?? null,
          size_bytes: s?.size_bytes ?? null,
          has_inline_text: !!s?.has_inline_text,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Attach failed.");
    } finally {
      setAttaching(false);
      if (attachRef.current) attachRef.current.value = "";
    }
  }

  function removeAttachment(id: number) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  async function send() {
    if (!input.trim() || sending) return;
    // Ensure we have a conversation to send into.
    let targetId = activeId;
    if (targetId == null) {
      try {
        const c = await api.post<ConversationSummary>(
          "/api/v1/companion/conversations",
          { title: null },
        );
        setConversations((prev) => [c, ...prev]);
        targetId = c.id;
        setActiveId(c.id);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(LS_ACTIVE_KEY, String(c.id));
        }
      } catch (e) {
        setError("Couldn't start a conversation.");
        return;
      }
    }

    setSending(true);
    setError(null);
    const content = input;
    setInput("");

    const optimisticUserId = -Date.now();
    const tempAssistantId = optimisticUserId + 1;
    const now = new Date().toISOString();
    setDetail((prev) => {
      const base: ConversationDetail =
        prev && prev.id === targetId
          ? prev
          : {
              id: targetId as number,
              title: null,
              summary: null,
              pinned: false,
              related_tracked_job_id: null,
              created_at: now,
              updated_at: now,
              claude_session_id: null,
              messages: [],
            };
      return {
        ...base,
        messages: [
          ...base.messages,
          {
            id: optimisticUserId,
            conversation_id: base.id,
            role: "user",
            content_md: content,
            skill_invoked: null,
            tool_calls: null,
            tool_results: null,
            created_at: now,
          },
          {
            id: tempAssistantId,
            conversation_id: base.id,
            role: "assistant",
            content_md: "",
            skill_invoked: null,
            tool_calls: null,
            tool_results: null,
            created_at: now,
          },
        ],
      };
    });

    try {
      const attachedIds = attachments.map((a) => a.id);
      const res = await fetch(
        apiUrl(
          `/api/v1/companion/conversations/${targetId}/messages-stream`,
        ),
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content,
            attached_document_ids: attachedIds.length ? attachedIds : null,
          }),
        },
      );
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantText = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let ev: {
            type: string;
            text?: string;
            message?: string;
          };
          try {
            ev = JSON.parse(payload);
          } catch {
            continue;
          }
          if (ev.type === "text_delta" && typeof ev.text === "string") {
            assistantText += ev.text;
            setDetail((prev) => {
              if (!prev) return prev;
              return {
                ...prev,
                messages: prev.messages.map((m) =>
                  m.id === tempAssistantId
                    ? { ...m, content_md: assistantText }
                    : m,
                ),
              };
            });
          } else if (ev.type === "error" && typeof ev.message === "string") {
            setError(ev.message);
          }
        }
      }
      // Reload conversation to get real IDs/meta, and refresh the switcher.
      try {
        const fresh = await api.get<ConversationDetail>(
          `/api/v1/companion/conversations/${targetId}`,
        );
        setDetail(fresh);
        const list = await api.get<ConversationSummary[]>(
          "/api/v1/companion/conversations",
        );
        setConversations(list);
      } catch {
        /* non-fatal */
      }
      // Clear attachments after a successful exchange.
      setAttachments([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed.");
      setInput(content);
      // Drop the optimistic bubbles.
      setDetail((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          messages: prev.messages.filter(
            (m) => m.id !== optimisticUserId && m.id !== tempAssistantId,
          ),
        };
      });
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  if (authed === null || authed === false) return null;
  if (HIDDEN_PATHS.has(pathname)) return null;

  // Collapsed: just a pill button in the bottom-right.
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => persistOpen(true)}
        className="fixed bottom-4 right-4 z-40 jsp-btn-primary shadow-lg flex items-center gap-2"
        title="Open Companion chat"
      >
        <span className="text-base">💬</span>
        <span className="text-xs uppercase tracking-wider">Pal</span>
      </button>
    );
  }

  const activeTitle = detail?.title ?? "Untitled conversation";

  return (
    <div className="fixed bottom-4 right-4 z-40 w-[min(420px,calc(100vw-2rem))] h-[min(620px,calc(100vh-6rem))] jsp-card shadow-2xl flex flex-col overflow-hidden">
      <header className="flex items-center gap-2 px-3 py-2 border-b border-corp-border bg-corp-surface2">
        <div className="relative min-w-0 flex-1">
          <button
            type="button"
            className="text-left w-full flex items-center gap-1 hover:text-corp-accent"
            onClick={() => setSwitcherOpen((v) => !v)}
            title="Switch conversation"
          >
            <span className="truncate text-sm">{activeTitle}</span>
            <span className="text-[10px] text-corp-muted">▾</span>
          </button>
          {switcherOpen ? (
            <div className="absolute top-full mt-1 left-0 right-0 max-h-60 overflow-y-auto jsp-card border-corp-border z-50 shadow-xl">
              <button
                type="button"
                className="w-full text-left px-3 py-2 text-xs uppercase tracking-wider text-corp-accent hover:bg-corp-surface2 border-b border-corp-border"
                onClick={() => {
                  createAndFocus();
                  setSwitcherOpen(false);
                }}
              >
                + New conversation
              </button>
              {conversations.length === 0 ? (
                <div className="px-3 py-2 text-xs text-corp-muted">
                  No conversations yet.
                </div>
              ) : (
                conversations.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={`w-full text-left px-3 py-2 text-sm hover:bg-corp-surface2 ${
                      c.id === activeId ? "text-corp-accent" : ""
                    }`}
                    onClick={() => selectConversation(c.id)}
                  >
                    <div className="truncate">{c.title ?? "Untitled"}</div>
                    <div className="text-[10px] text-corp-muted">
                      {new Date(c.updated_at).toLocaleString()}
                    </div>
                  </button>
                ))
              )}
            </div>
          ) : null}
        </div>
        <Link
          href="/companion"
          className="jsp-btn-ghost text-xs"
          title="Open full Companion view"
        >
          ⤢
        </Link>
        <button
          type="button"
          className="jsp-btn-ghost text-xs"
          onClick={() => persistOpen(false)}
          title="Hide dock"
        >
          ▁
        </button>
      </header>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3 space-y-2 bg-corp-bg"
      >
        {!detail || detail.messages.length === 0 ? (
          <div className="text-xs text-corp-muted text-center mt-4 space-y-2">
            <p>
              Say hi to Pal! Gosh, it&apos;s going to be a productive day.
            </p>
            <p className="italic">Enter sends. Shift+Enter for a newline.</p>
          </div>
        ) : (
          detail.messages.map((m) => <DockBubble key={m.id} message={m} />)
        )}
        {sending ? (
          <div className="flex justify-start">
            <div className="jsp-card px-2 py-1 text-xs text-corp-muted animate-pulse">
              Pal is thinking...
            </div>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="px-3 py-1 border-t border-corp-danger/40 text-[11px] text-corp-danger bg-corp-danger/10">
          {error}
        </div>
      ) : null}

      {attachments.length > 0 ? (
        <div className="border-t border-corp-border px-2 py-1 flex flex-wrap gap-1 bg-corp-surface">
          {attachments.map((a) => (
            <span
              key={a.id}
              className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-corp-surface2 border border-corp-border"
              title={a.has_inline_text ? "text extracted" : "binary — content not inlined"}
            >
              <span>📎</span>
              <span className="max-w-[14ch] truncate">
                {a.filename ?? a.title}
              </span>
              {!a.has_inline_text ? (
                <span className="text-corp-accent2">bin</span>
              ) : null}
              <button
                type="button"
                className="text-corp-muted hover:text-corp-danger"
                onClick={() => removeAttachment(a.id)}
                aria-label={`Remove ${a.title}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <div className="border-t border-corp-border p-2 flex gap-2 items-end bg-corp-surface">
        <label
          className={`jsp-btn-ghost text-xs cursor-pointer inline-flex ${
            attaching ? "opacity-50 pointer-events-none" : ""
          }`}
          title="Attach a file"
        >
          {attaching ? "..." : "📎"}
          <input
            ref={attachRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) attachFile(f);
            }}
          />
        </label>
        <textarea
          className="jsp-input flex-1 min-h-[2.5rem] max-h-32 resize-none text-sm"
          placeholder="Message Pal..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={sending}
        />
        <button
          type="button"
          className="jsp-btn-primary text-xs"
          onClick={send}
          disabled={sending || !input.trim()}
        >
          {sending ? "..." : "Send"}
        </button>
      </div>
    </div>
  );
}

function DockBubble({ message }: { message: ConversationMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] px-2.5 py-1.5 rounded-lg whitespace-pre-wrap text-[13px] ${
          isUser
            ? "bg-corp-accent text-corp-bg"
            : isSystem
              ? "border border-corp-danger/40 text-corp-danger bg-corp-danger/10"
              : "jsp-card"
        }`}
      >
        {message.content_md ?? ""}
      </div>
    </div>
  );
}
