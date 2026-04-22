"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError, apiUrl } from "@/lib/api";
import type {
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
} from "@/lib/types";

type AttachedDoc = {
  id: number;
  title: string;
  filename: string | null;
  size_bytes: number | null;
  extracted_from: string | null;
  has_inline_text: boolean;
};

function formatSize(n: number | null): string {
  if (!n) return "";
  if (n > 1_000_000) return `${(n / 1_000_000).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

const QUICK_PROMPTS: { label: string; prompt: string }[] = [
  {
    label: "Log a job I just applied to",
    prompt:
      "I just applied to a job. Ask me for the details one at a time " +
      "(URL or title, company, date applied, status), then create the " +
      "TrackedJob via the API and log an ApplicationEvent. Don't write " +
      "anything yet — confirm the extracted fields with me first.",
  },
  {
    label: "Fill gaps in my history",
    prompt:
      "Walk through my work experience, education, and skills via the " +
      "API and find entries with incomplete data — missing highlights, " +
      "end dates, skill links, etc. Ask me pointed questions one at a " +
      "time to fill them in, then update the records when I confirm.",
  },
  {
    label: "Strategize my pipeline",
    prompt:
      "Pull my tracked jobs and give me a short strategy read: which " +
      "applications are stalled, which should I follow up on, which " +
      "look like weak fits worth dropping.",
  },
  {
    label: "Draft an interview prep doc",
    prompt:
      "Pick one of my upcoming interview rounds. Pull the JD and my " +
      "history and draft a prep doc: likely questions, talking points " +
      "from my history, smart questions to ask them, and things to " +
      "watch for based on the JD analysis and company research.",
  },
];

type ClaudeHealth = {
  claude_cli_available: boolean;
  has_anthropic_api_key: boolean;
  has_oauth_session: boolean;
  authenticated: boolean;
  login_hint: string;
};

export default function CompanionPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [claudeHealth, setClaudeHealth] = useState<ClaudeHealth | null>(null);

  const refreshList = useCallback(async () => {
    try {
      const rs = await api.get<ConversationSummary[]>(
        "/api/v1/companion/conversations",
      );
      setConversations(rs);
      return rs;
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    refreshList().then((rs) => {
      if (rs.length > 0 && activeId == null) setActiveId(rs[0].id);
    });
    api.get<ClaudeHealth>("/health/claude").then(setClaudeHealth).catch(() => {
      /* non-fatal */
    });
  }, [refreshList, activeId]);

  useEffect(() => {
    if (activeId == null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    api
      .get<ConversationDetail>(`/api/v1/companion/conversations/${activeId}`)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  async function createConversation() {
    const conv = await api.post<ConversationSummary>(
      "/api/v1/companion/conversations",
      {},
    );
    await refreshList();
    setActiveId(conv.id);
  }

  async function deleteConversation(id: number) {
    if (!confirm("Delete this conversation?")) return;
    await api.delete(`/api/v1/companion/conversations/${id}`);
    if (activeId === id) setActiveId(null);
    await refreshList();
  }

  function onStreamingStart(
    userMsg: ConversationMessage,
    assistantPlaceholder: ConversationMessage,
  ) {
    setDetail((prev) =>
      prev
        ? {
            ...prev,
            messages: [...prev.messages, userMsg, assistantPlaceholder],
          }
        : prev,
    );
  }

  function onAssistantDelta(tempId: number, text: string) {
    setDetail((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        messages: prev.messages.map((m) =>
          m.id === tempId ? { ...m, content_md: text } : m,
        ),
      };
    });
  }

  function onAssistantMeta(
    tempId: number,
    tools: { name: string; input: unknown }[],
  ) {
    setDetail((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        messages: prev.messages.map((m) =>
          m.id === tempId ? { ...m, tool_calls: tools } : m,
        ),
      };
    });
  }

  function onStreamingDone(fresh: ConversationDetail) {
    setDetail(fresh);
    setConversations((prev) =>
      prev
        .map((c) =>
          c.id === fresh.id
            ? {
                id: fresh.id,
                title: fresh.title,
                summary: fresh.summary,
                pinned: fresh.pinned,
                related_tracked_job_id: fresh.related_tracked_job_id,
                created_at: fresh.created_at,
                updated_at: fresh.updated_at,
              }
            : c,
        )
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    );
  }

  function onStreamingLocalDone(
    tempId: number,
    finalText: string,
    skillsInferred: string[],
  ) {
    setDetail((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        messages: prev.messages.map((m) =>
          m.id === tempId
            ? {
                ...m,
                content_md: finalText,
                tool_results: skillsInferred.length
                  ? { ...(m.tool_results as object | null), skills_inferred: skillsInferred }
                  : m.tool_results,
              }
            : m,
        ),
      };
    });
  }

  function onStreamingAbort(userTempId: number, assistantTempId: number) {
    setDetail((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        messages: prev.messages.filter(
          (m) => m.id !== userTempId && m.id !== assistantTempId,
        ),
      };
    });
  }

  return (
    <PageShell
      title="Companion"
      subtitle="Your loyal and only mildly ironic corporate career assistant — speaks to Claude Code on your behalf."
      actions={
        <button className="jsp-btn-primary" onClick={createConversation}>
          + New Conversation
        </button>
      }
    >
      {claudeHealth && !claudeHealth.authenticated ? (
        <ClaudeLoginPanel
          onAuthed={() => {
            api.get<ClaudeHealth>("/health/claude").then(setClaudeHealth).catch(() => {});
          }}
        />
      ) : null}
      <div className="grid grid-cols-[260px_1fr] gap-4 h-[calc(100vh-12rem)]">
        <ConversationsList
          conversations={conversations}
          loading={loadingList}
          activeId={activeId}
          onSelect={setActiveId}
          onDelete={deleteConversation}
        />
        <ChatPane
          onStreamingStart={onStreamingStart}
          onAssistantDelta={onAssistantDelta}
          onAssistantMeta={onAssistantMeta}
          onStreamingDone={onStreamingDone}
          onStreamingLocalDone={onStreamingLocalDone}
          onStreamingAbort={onStreamingAbort}
          detail={detail}
          loading={loadingDetail}
          onNew={createConversation}
        />
      </div>
    </PageShell>
  );
}

// ---------- Conversations list ------------------------------------------------

function ConversationsList({
  conversations,
  loading,
  activeId,
  onSelect,
  onDelete,
}: {
  conversations: ConversationSummary[];
  loading: boolean;
  activeId: number | null;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <aside className="jsp-card overflow-y-auto">
      {loading ? (
        <div className="p-3 text-xs text-corp-muted">Loading...</div>
      ) : conversations.length === 0 ? (
        <div className="p-3 text-xs text-corp-muted">
          No conversations yet. Create one to begin.
        </div>
      ) : (
        <ul>
          {conversations.map((c) => (
            <li
              key={c.id}
              className={`group relative border-b border-corp-border last:border-b-0 ${
                c.id === activeId ? "bg-corp-surface2" : "hover:bg-corp-surface2"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                className="w-full text-left px-3 py-2.5 pr-9 block"
              >
                <div className="text-sm text-corp-text truncate">
                  {c.title ?? "Untitled"}
                </div>
                <div className="text-[10px] uppercase tracking-wider text-corp-muted mt-0.5">
                  {new Date(c.updated_at).toLocaleString()}
                </div>
              </button>
              <button
                type="button"
                onClick={() => onDelete(c.id)}
                className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 text-corp-muted hover:text-corp-danger text-xs"
                title="Delete"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

// ---------- Chat pane ---------------------------------------------------------

function ChatPane({
  detail,
  loading,
  onStreamingStart,
  onAssistantDelta,
  onAssistantMeta,
  onStreamingDone,
  onStreamingLocalDone,
  onStreamingAbort,
  onNew,
}: {
  detail: ConversationDetail | null;
  loading: boolean;
  onStreamingStart: (
    userMsg: ConversationMessage,
    assistantPlaceholder: ConversationMessage,
  ) => void;
  onAssistantDelta: (tempId: number, text: string) => void;
  onAssistantMeta: (
    tempId: number,
    tools: { name: string; input: unknown }[],
  ) => void;
  onStreamingDone: (fresh: ConversationDetail) => void;
  onStreamingLocalDone: (
    tempId: number,
    finalText: string,
    skillsInferred: string[],
  ) => void;
  onStreamingAbort: (userTempId: number, assistantTempId: number) => void;
  onNew: () => void;
}) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<AttachedDoc[]>([]);
  const [attaching, setAttaching] = useState(false);
  const attachRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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
          extracted_from?: string | null;
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
          extracted_from: s?.extracted_from ?? null,
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

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [detail?.messages.length, sending]);

  async function send() {
    if (!detail || !input.trim() || sending) return;
    setError(null);
    setSending(true);
    const content = input;
    setInput("");

    // Optimistic user message so the bubble appears instantly.
    const optimisticUserId = -Date.now();
    const tempAssistantId = optimisticUserId + 1;
    const now = new Date().toISOString();
    onStreamingStart(
      {
        id: optimisticUserId,
        conversation_id: detail.id,
        role: "user",
        content_md: content,
        skill_invoked: null,
        tool_calls: null,
        tool_results: null,
        created_at: now,
      },
      {
        id: tempAssistantId,
        conversation_id: detail.id,
        role: "assistant",
        content_md: "",
        skill_invoked: null,
        tool_calls: null,
        tool_results: null,
        created_at: now,
      },
    );

    try {
      const attachedIds = attachments.map((a) => a.id);
      const res = await fetch(
        apiUrl(`/api/v1/companion/conversations/${detail.id}/messages-stream`),
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
      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantText = "";
      let skillsInferred: string[] = [];
      const toolsUsed: { name: string; input: unknown }[] = [];

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
            name?: string;
            input?: unknown;
            message?: string;
            skills_inferred?: string[];
            [k: string]: unknown;
          };
          try {
            ev = JSON.parse(payload);
          } catch {
            continue;
          }
          if (ev.type === "text_delta" && typeof ev.text === "string") {
            assistantText += ev.text;
            onAssistantDelta(tempAssistantId, assistantText);
          } else if (ev.type === "tool_use") {
            toolsUsed.push({ name: String(ev.name ?? ""), input: ev.input });
            onAssistantMeta(tempAssistantId, toolsUsed);
          } else if (ev.type === "error" && typeof ev.message === "string") {
            setError(ev.message);
          } else if (ev.type === "done") {
            if (Array.isArray(ev.skills_inferred)) {
              skillsInferred = ev.skills_inferred as string[];
            }
          }
        }
      }

      // Reload the full conversation so we get real IDs / persisted metadata.
      try {
        const fresh = await api.get<ConversationDetail>(
          `/api/v1/companion/conversations/${detail.id}`,
        );
        onStreamingDone(fresh);
      } catch {
        // Fall back to what we have in memory.
        onStreamingLocalDone(tempAssistantId, assistantText, skillsInferred);
      }
      // Clear attachments after a successful exchange.
      setAttachments([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error.");
      setInput(content);
      onStreamingAbort(optimisticUserId, tempAssistantId);
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

  if (!detail) {
    return (
      <section className="jsp-card p-8 flex flex-col items-center justify-center text-center">
        <h2 className="text-lg font-semibold text-corp-accent mb-2">
          No conversation selected
        </h2>
        <p className="text-sm text-corp-muted max-w-sm mb-4">
          Start a new one to begin dictation. All responses are generated by the
          Claude Code CLI running inside the backend container.
        </p>
        <button className="jsp-btn-primary" onClick={onNew}>
          + New Conversation
        </button>
      </section>
    );
  }

  return (
    <section className="jsp-card flex flex-col min-h-0">
      <header className="px-4 py-3 border-b border-corp-border">
        <div className="text-sm font-medium">{detail.title ?? "Untitled"}</div>
        {detail.claude_session_id ? (
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mt-0.5">
            session · {detail.claude_session_id.slice(0, 12)}
          </div>
        ) : (
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mt-0.5">
            fresh session
          </div>
        )}
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading ? (
          <p className="text-corp-muted text-sm">Loading...</p>
        ) : detail.messages.length === 0 && !sending ? (
          <div className="text-corp-muted text-sm text-center mt-8 space-y-4">
            <p>
              The Companion is ready. Ask about your job search, request a
              resume review, or just say hi.
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {QUICK_PROMPTS.map((qp) => (
                <button
                  key={qp.label}
                  type="button"
                  className="jsp-btn-ghost text-xs"
                  onClick={() => setInput(qp.prompt)}
                  title={qp.prompt}
                >
                  {qp.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {detail.messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {sending ? (
          <div className="flex justify-start">
            <div className="jsp-card px-3 py-2 text-sm text-corp-muted animate-pulse">
              Companion is thinking...
            </div>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="px-4 py-2 border-t border-corp-danger/40 text-sm text-corp-danger bg-corp-danger/10">
          {error}
        </div>
      ) : null}

      {attachments.length > 0 ? (
        <div className="border-t border-corp-border px-3 py-2 flex flex-wrap gap-1.5">
          {attachments.map((a) => (
            <span
              key={a.id}
              className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-corp-surface2 border border-corp-border"
              title={
                a.has_inline_text
                  ? `${a.extracted_from} · text extracted`
                  : "Binary file — content not inlined"
              }
            >
              <span>📎</span>
              <span className="max-w-[18ch] truncate">
                {a.filename ?? a.title}
              </span>
              {a.size_bytes ? (
                <span className="text-corp-muted">· {formatSize(a.size_bytes)}</span>
              ) : null}
              {!a.has_inline_text ? (
                <span className="text-corp-accent2 text-[10px]">binary</span>
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
      <div className="border-t border-corp-border p-3 flex gap-2 items-end">
        <label
          className={`jsp-btn-ghost cursor-pointer inline-flex ${
            attaching ? "opacity-50 pointer-events-none" : ""
          }`}
          title="Attach a file (PDF, DOCX, HTML, txt, md — up to 25 MB)"
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
          className="jsp-input flex-1 min-h-[3rem] max-h-40 resize-none"
          placeholder="Message the Companion... (Enter to send, Shift+Enter for newline)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={sending}
        />
        <button
          type="button"
          className="jsp-btn-primary"
          onClick={send}
          disabled={sending || !input.trim()}
        >
          {sending ? "..." : "Send"}
        </button>
      </div>
    </section>
  );
}

// ---------- Claude Code OAuth login panel ------------------------------------

function ClaudeLoginPanel({ onAuthed }: { onAuthed: () => void }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [promptReady, setPromptReady] = useState(false);
  const [code, setCode] = useState("");
  const [finished, setFinished] = useState(false);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const [status, setStatus] = useState<"idle" | "starting" | "streaming" | "submitting">("idle");
  const [error, setError] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [liveStatus, setLiveStatus] = useState<string>("Starting CLI…");
  const [pasteToken, setPasteToken] = useState("");
  const [savingToken, setSavingToken] = useState(false);

  async function submitPastedToken(e: React.FormEvent) {
    e.preventDefault();
    const t = pasteToken.trim();
    if (!t) return;
    setError(null);
    setSavingToken(true);
    try {
      await api.post("/api/v1/auth/claude-login/token", { token: t });
      setPasteToken("");
      onAuthed();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 422
            ? "That doesn't look like a valid sk-ant-oat01- token."
            : `Save failed (HTTP ${err.status}).`
          : "Save failed.",
      );
    } finally {
      setSavingToken(false);
    }
  }

  async function startLogin() {
    setError(null);
    setStatus("starting");
    setSessionId(null);
    setAuthUrl(null);
    setPromptReady(false);
    setCode("");
    setFinished(false);
    setExitCode(null);
    setLogLines([]);
    try {
      const res = await api.post<{ session_id: string }>(
        "/api/v1/auth/claude-login/start",
      );
      setSessionId(res.session_id);
      setStatus("streaming");
    } catch (err) {
      setStatus("idle");
      setError(err instanceof ApiError ? `Start failed (HTTP ${err.status}).` : "Failed to start login.");
    }
  }

  useEffect(() => {
    if (!sessionId) return;
    const url = apiUrl(`/api/v1/auth/claude-login/${sessionId}/stream`);
    const es = new EventSource(url, { withCredentials: true });

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as {
          event: string;
          url?: string;
          text?: string;
          code?: number;
          message?: string;
        };
        if (data.event === "url" && data.url) setAuthUrl(data.url);
        else if (data.event === "prompt") setPromptReady(true);
        else if (data.event === "spawned") setLiveStatus("CLI subprocess spawned — waiting for Claude to print the auth URL…");
        else if (data.event === "opened") setLiveStatus("SSE stream connected. Waiting for subprocess…");
        else if (data.event === "exit") {
          setFinished(true);
          setExitCode(data.code ?? null);
          es.close();
          if ((data.code ?? 1) === 0) onAuthed();
        } else if (data.event === "error") {
          setError(data.message ?? "Subprocess error.");
        } else if (data.event === "chunk" && data.text) {
          setLogLines((prev) => {
            const next = [...prev, data.text!.trim()].filter(Boolean);
            return next.slice(-10);
          });
        }
      } catch {
        /* ignore malformed events */
      }
    };
    es.onerror = () => {
      // EventSource auto-retries; we let the exit event drive final state.
    };
    return () => es.close();
  }, [sessionId, onAuthed]);

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    if (!sessionId || !code.trim()) return;
    setStatus("submitting");
    setError(null);
    try {
      await api.post(`/api/v1/auth/claude-login/${sessionId}/input`, {
        line: code.trim(),
      });
      setCode("");
    } catch (err) {
      setError(err instanceof ApiError ? `Paste failed (HTTP ${err.status}).` : "Paste failed.");
    } finally {
      setStatus("streaming");
    }
  }

  async function cancel() {
    if (!sessionId) return;
    try {
      await api.post(`/api/v1/auth/claude-login/${sessionId}/cancel`);
    } catch {
      /* ignore */
    }
    setSessionId(null);
    setStatus("idle");
    setFinished(false);
  }

  const success = finished && exitCode === 0;
  const failed = finished && exitCode !== 0;

  return (
    <div className="jsp-card p-4 mb-4 border-l-4 border-l-corp-accent2">
      <div className="text-sm font-medium text-corp-accent2 mb-1">
        Claude Code is not yet authenticated
      </div>
      <p className="text-sm text-corp-text">
        Run the standard OAuth flow from here — the CLI is launched inside the
        isolated API container and credentials persist in its config volume.
      </p>

      {status === "idle" ? (
        <div className="mt-3 flex items-center gap-2">
          <button className="jsp-btn-primary" onClick={startLogin}>
            Launch OAuth login
          </button>
          <span className="text-xs text-corp-muted">
            Or set <code>ANTHROPIC_API_KEY</code> in <code>.env</code>.
          </span>
        </div>
      ) : null}

      {sessionId && !finished ? (
        <div className="mt-3 space-y-3">
          {authUrl ? (
            <div>
              <div className="text-xs uppercase tracking-wider text-corp-muted mb-1">
                Step 1 — authorize in your browser
              </div>
              <a
                href={authUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="jsp-btn-primary inline-block"
              >
                Open OAuth page →
              </a>
              <div className="text-xs text-corp-muted mt-2 break-all">
                {authUrl}
              </div>
            </div>
          ) : (
            <div className="text-sm text-corp-muted space-y-1">
              <div>{liveStatus}</div>
              {logLines.length > 0 ? (
                <pre className="text-[10px] text-corp-muted/80 bg-corp-surface2 border border-corp-border rounded p-2 whitespace-pre-wrap max-h-40 overflow-auto">
                  {logLines.join("\n")}
                </pre>
              ) : (
                <div className="text-[11px] text-corp-muted italic">
                  No output from the CLI yet. If this stays blank for a while,
                  run <code>docker compose exec -it api claude setup-token</code> on
                  the server to test the CLI directly, or paste a token manually
                  below.
                </div>
              )}
            </div>
          )}

          {promptReady ? (
            <form onSubmit={submitCode} className="space-y-2">
              <div className="text-xs uppercase tracking-wider text-corp-muted">
                Step 2 — paste the code the browser shows
              </div>
              <div className="flex gap-2">
                <input
                  className="jsp-input flex-1 font-mono"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="Paste auth code here"
                  autoFocus
                />
                <button
                  type="submit"
                  className="jsp-btn-primary"
                  disabled={status === "submitting" || !code.trim()}
                >
                  Submit
                </button>
              </div>
            </form>
          ) : authUrl ? (
            <div className="text-xs text-corp-muted italic">
              Waiting for the CLI to request a code...
            </div>
          ) : null}

          <div className="flex items-center gap-3">
            <button className="jsp-btn-ghost" type="button" onClick={cancel}>
              Cancel
            </button>
            {logLines.length > 0 ? (
              <span className="text-[10px] text-corp-muted truncate">
                {logLines[logLines.length - 1]}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {success ? (
        <div className="mt-3 text-sm text-corp-ok">
          ✓ Authenticated. Refreshing Companion...
        </div>
      ) : null}
      {failed ? (
        <div className="mt-3 space-y-2">
          <div className="text-sm text-corp-danger">
            Login exited with code {exitCode}. Try again.
          </div>
          <button className="jsp-btn-primary" onClick={startLogin}>
            Retry
          </button>
        </div>
      ) : null}
      {error ? (
        <div className="mt-3 text-sm text-corp-danger">{error}</div>
      ) : null}

      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-corp-muted hover:text-corp-text">
          Or paste a token you already generated
        </summary>
        <div className="mt-2 pl-1">
          <p className="text-xs text-corp-muted mb-2">
            Generate one yourself with{" "}
            <code>docker compose exec -it api claude setup-token</code> and
            paste it below. Kept locally in the container&apos;s config volume.
          </p>
          <form onSubmit={submitPastedToken} className="flex gap-2">
            <input
              type="password"
              className="jsp-input flex-1 font-mono"
              placeholder="sk-ant-oat01-..."
              value={pasteToken}
              onChange={(e) => setPasteToken(e.target.value)}
              autoComplete="off"
            />
            <button
              type="submit"
              className="jsp-btn-primary"
              disabled={savingToken || !pasteToken.trim()}
            >
              {savingToken ? "..." : "Save"}
            </button>
          </form>
        </div>
      </details>
    </div>
  );
}

function MessageBubble({ message }: { message: ConversationMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  // Pull cached metadata out of tool_results (set by the backend on persist).
  const toolResults = (message.tool_results ?? null) as
    | {
        meta?: {
          cost_usd?: number | null;
          duration_ms?: number | null;
          num_turns?: number | null;
        } | null;
        skills_inferred?: string[] | null;
      }
    | null;
  const meta = toolResults?.meta ?? null;
  const skillsInferred = toolResults?.skills_inferred ?? null;

  const metaBits: string[] = [];
  if (meta?.num_turns) metaBits.push(`${meta.num_turns} turn${meta.num_turns === 1 ? "" : "s"}`);
  if (meta?.duration_ms)
    metaBits.push(
      meta.duration_ms >= 1000
        ? `${(meta.duration_ms / 1000).toFixed(1)}s`
        : `${meta.duration_ms}ms`,
    );
  if (meta?.cost_usd != null) metaBits.push(`$${meta.cost_usd.toFixed(3)}`);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`px-3 py-2 rounded-lg whitespace-pre-wrap text-sm ${
            isUser
              ? "bg-corp-accent text-corp-bg"
              : isSystem
                ? "border border-corp-danger/40 text-corp-danger bg-corp-danger/10"
                : "jsp-card"
          }`}
        >
          {message.content_md ?? ""}
        </div>
        {!isUser && !isSystem && (skillsInferred?.length || metaBits.length) ? (
          <div className="flex flex-wrap gap-1 items-center text-[10px] text-corp-muted">
            {skillsInferred?.map((s) => (
              <span
                key={s}
                className="inline-block px-1.5 py-0.5 rounded bg-corp-surface2 border border-corp-border"
              >
                {s}
              </span>
            ))}
            {metaBits.length ? (
              <span className="italic">{metaBits.join(" · ")}</span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
