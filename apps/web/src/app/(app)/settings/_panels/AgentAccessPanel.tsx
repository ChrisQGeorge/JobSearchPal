"use client";

// Settings → Agent Access: mint / revoke tokens for external agents that
// talk to the app's MCP endpoint (/api/v1/mcp). Tokens are shown once.

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type AgentToken = {
  id: string;
  name: string;
  scope: "read" | "read_write";
  hint: string;
  created_at: string;
  last_used_at: string | null;
};

type TokensOut = {
  tokens: AgentToken[];
  tools: { name: string; write: boolean }[];
};

export function AgentAccessPanel() {
  const [data, setData] = useState<TokensOut | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "read_write">("read");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const endpoint =
    typeof window !== "undefined" ? `${window.location.origin}/api/v1/mcp` : "/api/v1/mcp";

  async function load() {
    try {
      setData(await api.get<TokensOut>("/api/v1/mcp-tokens"));
    } catch {
      setMsg("Could not load agent tokens.");
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function create() {
    setBusy(true);
    setMsg(null);
    try {
      const out = await api.post<{ token: string }>("/api/v1/mcp-tokens", {
        name: name.trim() || "agent",
        scope,
      });
      setFresh(out.token);
      setName("");
      await load();
    } catch (e) {
      setMsg(e instanceof ApiError ? `Create failed (HTTP ${e.status}).` : "Create failed.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    if (!window.confirm("Revoke this token? Agents using it lose access immediately.")) return;
    try {
      await api.delete(`/api/v1/mcp-tokens/${id}`);
      await load();
    } catch {
      setMsg("Revoke failed.");
    }
  }

  const configSnippet = JSON.stringify(
    {
      mcpServers: {
        "job-search-pal": {
          type: "http",
          url: endpoint,
          headers: { Authorization: `Bearer ${fresh ?? "jspmcp_…"}` },
        },
      },
    },
    null,
    2,
  );

  const readTools = data?.tools.filter((t) => !t.write).map((t) => t.name) ?? [];
  const writeTools = data?.tools.filter((t) => t.write).map((t) => t.name) ?? [];

  return (
    <div className="space-y-4">
      <div className="jsp-card p-4 space-y-2">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">
          MCP server for external agents
        </h3>
        <p className="text-xs text-corp-muted">
          Agents connect over MCP (Streamable HTTP) to the endpoint below with a
          bearer token. <strong>Read</strong> tokens can only look;{" "}
          <strong>read/write</strong> tokens can also create, update, triage, rescore,
          and queue documents — with the same rules and side effects as this UI.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <code className="text-xs px-2 py-1 rounded bg-corp-surface2 border border-corp-border break-all">
            {endpoint}
          </code>
          <button
            type="button"
            className="jsp-btn-ghost text-xs"
            onClick={() => void navigator.clipboard?.writeText(endpoint)}
          >
            Copy
          </button>
        </div>
      </div>

      <div className="jsp-card p-4 space-y-3">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">New token</h3>
        <div className="flex flex-wrap gap-2 items-end">
          <div className="flex-1 min-w-[160px]">
            <label className="jsp-label">Name</label>
            <input
              className="jsp-input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. research-agent"
              disabled={busy}
            />
          </div>
          <div>
            <label className="jsp-label">Access</label>
            <select
              className="jsp-input"
              value={scope}
              onChange={(e) => setScope(e.target.value as "read" | "read_write")}
              disabled={busy}
            >
              <option value="read">Read only</option>
              <option value="read_write">Read / write / update</option>
            </select>
          </div>
          <button type="button" className="jsp-btn-primary" onClick={create} disabled={busy}>
            {busy ? "Creating…" : "Create token"}
          </button>
        </div>
        {fresh ? (
          <div className="rounded border border-corp-accent/50 bg-corp-accent/10 p-3 space-y-2">
            <p className="text-xs">
              Copy this token now — it won&apos;t be shown again.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="text-xs break-all">{fresh}</code>
              <button
                type="button"
                className="jsp-btn-ghost text-xs"
                onClick={() => void navigator.clipboard?.writeText(fresh)}
              >
                Copy
              </button>
              <button type="button" className="jsp-btn-ghost text-xs" onClick={() => setFresh(null)}>
                Done
              </button>
            </div>
          </div>
        ) : null}
        <div>
          <label className="jsp-label">Client config (Claude Code / most MCP clients)</label>
          <pre className="text-[11px] p-2 rounded bg-corp-surface2 border border-corp-border overflow-x-auto">
            {configSnippet}
          </pre>
        </div>
        {msg ? <p className="text-xs text-corp-danger">{msg}</p> : null}
      </div>

      <div className="jsp-card p-4">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">Active tokens</h3>
        {!data || data.tokens.length === 0 ? (
          <p className="text-xs text-corp-muted">No agent tokens yet.</p>
        ) : (
          <ul className="divide-y divide-corp-border">
            {data.tokens.map((t) => (
              <li key={t.id} className="py-2 flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium">{t.name}</span>
                <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border border-corp-border text-corp-muted">
                  {t.scope === "read_write" ? "read/write" : "read"}
                </span>
                <span className="text-[11px] text-corp-muted">…{t.hint}</span>
                <span className="text-[11px] text-corp-muted ml-auto">
                  {t.last_used_at
                    ? `used ${new Date(t.last_used_at).toLocaleString()}`
                    : "never used"}
                </span>
                <button
                  type="button"
                  className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                  onClick={() => revoke(t.id)}
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
        {data ? (
          <p className="text-[11px] text-corp-muted mt-3">
            Read tools: {readTools.join(", ")}.
            <br />
            Write tools: {writeTools.join(", ")}.
          </p>
        ) : null}
      </div>
    </div>
  );
}
