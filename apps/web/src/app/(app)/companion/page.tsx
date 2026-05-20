"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AnalyzeEntityDetailPanel } from "@/components/AnalyzeEntityDetailPanel";
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

  // Deep-link: when /companion is opened with ?conv=<id> (from the
  // History Editor's Analyze button, or any future caller), jump
  // straight to that conversation. Read straight from
  // window.location to avoid forcing the route off static prerender,
  // which `useSearchParams` would do.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("conv");
    if (!raw) return;
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    setActiveId(n);
    refreshList();
  }, [refreshList]);

  useEffect(() => {
    if (activeId == null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function loadOnce() {
      try {
        const d = await api.get<ConversationDetail>(
          `/api/v1/companion/conversations/${activeId}`,
        );
        if (cancelled) return;
        setDetail(d);
        // If the most recent message is from the user, the Companion's
        // reply is still being generated in the background (e.g. for
        // analyze-entity, which fires Claude asynchronously). Poll
        // every 3s until an assistant / system message lands.
        const last = d.messages[d.messages.length - 1];
        if (last && last.role === "user") {
          timer = setTimeout(loadOnce, 3_000);
        }
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    }

    setLoadingDetail(true);
    loadOnce();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
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

  // If the active conversation was started via the History Editor's
  // "Analyze" button, the first user message carries a tool_calls
  // payload like { analyze_seed: { entity_type, entity_id } }. Pull it
  // out so we can render the live-entity-detail side panel alongside
  // the chat. Conversations created any other way (Companion + New,
  // etc.) won't have this and the panel doesn't render.
  const analyzeSeed = useMemo(() => {
    if (!detail || detail.messages.length === 0) return null;
    const first = detail.messages[0];
    const tc = first.tool_calls as
      | { analyze_seed?: { entity_type?: string; entity_id?: number } }
      | null
      | undefined;
    const seed = tc?.analyze_seed;
    if (!seed || !seed.entity_type || typeof seed.entity_id !== "number") {
      return null;
    }
    const allowed = new Set([
      "work",
      "education",
      "certification",
      "publication",
      "achievement",
      "volunteer",
      "project",
      "custom",
    ]);
    if (!allowed.has(seed.entity_type)) return null;
    return {
      entity_type: seed.entity_type as
        | "work"
        | "education"
        | "certification"
        | "publication"
        | "achievement"
        | "volunteer"
        | "project"
        | "custom",
      entity_id: seed.entity_id,
    };
  }, [detail]);

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
      <div
        className={`grid gap-4 h-[calc(100vh-12rem)] ${
          analyzeSeed
            ? "grid-cols-[240px_1fr_320px]"
            : "grid-cols-[260px_1fr]"
        }`}
      >
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
        {analyzeSeed ? (
          <AnalyzeEntityDetailPanel
            entityType={analyzeSeed.entity_type}
            entityId={analyzeSeed.entity_id}
          />
        ) : null}
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
  // Live activity log while a turn is streaming. Each entry is a one-line
  // breadcrumb of something the Companion just did — a tool call, the
  // start of text generation, etc. Cleared when sending finishes so the
  // mini activity panel auto-disappears once the response is fully on
  // screen. Capped to the most recent 8 entries so the panel stays small.
  type ActivityEntry = { id: number; kind: "tool" | "text" | "info"; label: string };
  const [activityLog, setActivityLog] = useState<ActivityEntry[]>([]);
  const activityCounterRef = useRef(0);
  function pushActivity(kind: ActivityEntry["kind"], label: string) {
    activityCounterRef.current += 1;
    const id = activityCounterRef.current;
    setActivityLog((prev) => {
      const next = [...prev, { id, kind, label }];
      return next.length > 8 ? next.slice(next.length - 8) : next;
    });
  }
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

  // Consume an SSE response body. Shared between `send()` (POST stream)
  // and the reattach effect (GET stream). Mutates the local accumulators
  // via the on*-callback signatures the caller passes in. Returns the
  // final assistant text + inferred skills the stream reported.
  async function consumeStream(
    body: ReadableStream<Uint8Array>,
    onText: (full: string) => void,
    onTools: (tools: { name: string; input: unknown }[]) => void,
  ): Promise<{ assistantText: string; skillsInferred: string[] }> {
    const reader = body.getReader();
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
          const isFirstTextChunk = assistantText.length === 0;
          assistantText += ev.text;
          onText(assistantText);
          if (isFirstTextChunk) {
            pushActivity("text", "Writing reply…");
          }
        } else if (ev.type === "tool_use") {
          toolsUsed.push({ name: String(ev.name ?? ""), input: ev.input });
          onTools(toolsUsed);
          const toolName = String(ev.name ?? "tool");
          const inp = (ev.input as Record<string, unknown> | undefined) ?? {};
          let summary: string;
          if (toolName === "Bash" && typeof inp.command === "string") {
            summary = `${toolName} · ${(inp.command as string).slice(0, 80)}`;
          } else if (toolName === "Read" && typeof inp.file_path === "string") {
            summary = `${toolName} · ${inp.file_path as string}`;
          } else if (toolName === "Grep" && typeof inp.pattern === "string") {
            summary = `${toolName} · /${inp.pattern as string}/`;
          } else if (toolName === "WebFetch" && typeof inp.url === "string") {
            summary = `${toolName} · ${inp.url as string}`;
          } else if (toolName === "WebSearch" && typeof inp.query === "string") {
            summary = `${toolName} · ${inp.query as string}`;
          } else {
            summary = toolName;
          }
          pushActivity("tool", summary);
        } else if (ev.type === "error" && typeof ev.message === "string") {
          setError(ev.message);
          pushActivity("info", `Error: ${ev.message.slice(0, 80)}`);
        } else if (ev.type === "done") {
          if (Array.isArray(ev.skills_inferred)) {
            skillsInferred = ev.skills_inferred as string[];
          }
        }
      }
    }
    return { assistantText, skillsInferred };
  }

  // Reattach to an in-flight chat run when the user opens a conversation
  // whose last message is `user`. The backend's chat task runs detached
  // from any HTTP request — if it's still going we can subscribe to
  // its event stream and pick up where the previous tab left off.
  // Otherwise the run is finished; the assistant message is already in
  // `detail.messages` on reload and there's nothing to do.
  const reattachedRef = useRef<number | null>(null);
  useEffect(() => {
    if (!detail || sending) return;
    const lastMsg = detail.messages[detail.messages.length - 1];
    if (!lastMsg || lastMsg.role !== "user") return;
    // Only attempt once per (conversation, user message) pair so we don't
    // hammer the endpoint with reconnect attempts.
    if (reattachedRef.current === lastMsg.id) return;
    reattachedRef.current = lastMsg.id;

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          apiUrl(
            `/api/v1/companion/conversations/${detail.id}/messages/${lastMsg.id}/stream`,
          ),
          { method: "GET", credentials: "include" },
        );
        if (cancelled) return;
        if (!res.ok || !res.body) return; // 404 = no live run; fall through to polling
        setSending(true);
        setActivityLog([]);
        const tempAssistantId = -Date.now();
        const now = new Date().toISOString();
        onStreamingStart(lastMsg, {
          id: tempAssistantId,
          conversation_id: detail.id,
          role: "assistant",
          content_md: "",
          skill_invoked: null,
          tool_calls: null,
          tool_results: null,
          created_at: now,
        });
        const { assistantText, skillsInferred } = await consumeStream(
          res.body,
          (txt) => onAssistantDelta(tempAssistantId, txt),
          (tools) => onAssistantMeta(tempAssistantId, tools),
        );
        if (cancelled) return;
        try {
          const fresh = await api.get<ConversationDetail>(
            `/api/v1/companion/conversations/${detail.id}`,
          );
          onStreamingDone(fresh);
        } catch {
          onStreamingLocalDone(tempAssistantId, assistantText, skillsInferred);
        }
      } catch {
        // Reattach is best-effort. Polling will catch the assistant
        // message when the background task persists it.
      } finally {
        if (!cancelled) {
          setSending(false);
          setActivityLog([]);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.id, detail?.messages.length]);

  async function send() {
    if (!detail || !input.trim() || sending) return;
    setError(null);
    setSending(true);
    setActivityLog([]); // fresh activity log per turn
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
      const { assistantText, skillsInferred } = await consumeStream(
        res.body,
        (txt) => onAssistantDelta(tempAssistantId, txt),
        (tools) => onAssistantMeta(tempAssistantId, tools),
      );

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
      // Stream died mid-flight (SSE socket dropped, proxy reset, etc.).
      // The backend persists the assistant message in the stream
      // generator's finally block, so the DB *may* have the final
      // text even though our SSE consumer never saw a clean `done`
      // event. Try one defensive re-fetch — if the persisted
      // assistant turn is there, surface it; otherwise abort the
      // optimistic UI bubbles as before so the user can retry.
      let recovered = false;
      try {
        const fresh = await api.get<ConversationDetail>(
          `/api/v1/companion/conversations/${detail.id}`,
        );
        const lastMsg = fresh.messages[fresh.messages.length - 1];
        if (lastMsg && lastMsg.role === "assistant") {
          onStreamingDone(fresh);
          recovered = true;
        }
      } catch {
        /* fall through to abort */
      }
      if (!recovered) {
        setError(err instanceof Error ? err.message : "Unexpected error.");
        setInput(content);
        onStreamingAbort(optimisticUserId, tempAssistantId);
      }
    } finally {
      setSending(false);
      // Auto-hide the activity panel — the final response is now in
      // the assistant bubble, so the breadcrumbs are no longer useful.
      setActivityLog([]);
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
            <div className="jsp-card px-3 py-2 text-xs text-corp-muted min-w-[16rem] max-w-md">
              <div className="flex items-center gap-2 mb-1">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-corp-accent animate-pulse" />
                <span className="uppercase tracking-wider text-corp-accent text-[10px]">
                  Companion working
                </span>
              </div>
              {activityLog.length === 0 ? (
                <div className="text-corp-muted">
                  Starting up — Claude subprocess spinning up…
                </div>
              ) : (
                <ul className="space-y-0.5 max-h-32 overflow-y-auto">
                  {activityLog.map((a) => (
                    <li
                      key={a.id}
                      className={`truncate ${
                        a.kind === "tool"
                          ? "text-corp-text"
                          : a.kind === "text"
                            ? "text-corp-accent"
                            : "text-corp-danger"
                      }`}
                      title={a.label}
                    >
                      <span className="text-corp-muted mr-1">
                        {a.kind === "tool" ? "→" : a.kind === "text" ? "✎" : "!"}
                      </span>
                      <span className="font-mono text-[11px]">{a.label}</span>
                    </li>
                  ))}
                </ul>
              )}
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
  // OAuth/subscription turns report cost_usd = 0 (no per-turn charge). Only
  // surface cost when it's actually nonzero — i.e. API-key billing mode.
  if (meta?.cost_usd != null && meta.cost_usd > 0)
    metaBits.push(`$${meta.cost_usd.toFixed(3)}`);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[80%] flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`px-3 py-2 rounded-lg text-sm ${
            isUser
              ? "bg-corp-accent text-corp-bg whitespace-pre-wrap"
              : isSystem
                ? "border border-corp-danger/40 text-corp-danger bg-corp-danger/10 whitespace-pre-wrap"
                : "jsp-card jsp-markdown"
          }`}
        >
          {isUser || isSystem ? (
            message.content_md ?? ""
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-corp-accent hover:underline"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {message.content_md ?? ""}
            </ReactMarkdown>
          )}
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
