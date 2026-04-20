"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError, apiUrl } from "@/lib/api";
import type {
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
  SendMessageResponse,
} from "@/lib/types";

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

  function onMessageExchanged(res: SendMessageResponse) {
    // Append both messages to the open conversation.
    setDetail((prev) =>
      prev
        ? {
            ...prev,
            messages: [...prev.messages, res.user_message, res.assistant_message],
          }
        : prev,
    );
    // Update the sidebar entry so the new title / updated_at reflects.
    setConversations((prev) =>
      prev.map((c) => (c.id === res.conversation.id ? res.conversation : c)).sort(
        (a, b) => b.updated_at.localeCompare(a.updated_at),
      ),
    );
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
          detail={detail}
          loading={loadingDetail}
          onMessageExchanged={onMessageExchanged}
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
  onMessageExchanged,
  onNew,
}: {
  detail: ConversationDetail | null;
  loading: boolean;
  onMessageExchanged: (res: SendMessageResponse) => void;
  onNew: () => void;
}) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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
    try {
      const res = await api.post<SendMessageResponse>(
        `/api/v1/companion/conversations/${detail.id}/messages`,
        { content },
      );
      onMessageExchanged(res);
    } catch (err) {
      if (err instanceof ApiError) {
        const detailMsg =
          typeof err.detail === "object" && err.detail && "detail" in err.detail
            ? String((err.detail as { detail: unknown }).detail)
            : `HTTP ${err.status}`;
        setError(detailMsg);
      } else {
        setError("Unexpected error.");
      }
      // Restore the draft so the user can retry.
      setInput(content);
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
          <p className="text-corp-muted text-sm text-center mt-8">
            The Companion is ready. Ask about your job search, request a resume
            review, or just say hi.
          </p>
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

      <div className="border-t border-corp-border p-3 flex gap-2 items-end">
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
            <div className="text-sm text-corp-muted">Starting CLI...</div>
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
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] px-3 py-2 rounded-lg whitespace-pre-wrap text-sm ${
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
