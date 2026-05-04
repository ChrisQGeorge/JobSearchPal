"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { api, apiUrl, ApiError } from "@/lib/api";

type ClaudeHealth = {
  claude_cli_available: boolean;
  has_anthropic_api_key: boolean;
  has_oauth_session: boolean;
  authenticated: boolean;
  login_hint: string;
};

export default function SettingsPage() {
  const router = useRouter();

  async function logout() {
    await api.post("/api/v1/auth/logout");
    router.replace("/login");
  }

  return (
    <PageShell
      title="Settings"
      subtitle="App configuration, API keys, themes, personas, and account."
      actions={
        <button className="jsp-btn-ghost text-corp-danger border-corp-danger/40" onClick={logout}>
          Log out
        </button>
      }
    >
      <div className="space-y-4">
        <ClaudeAuthPanel />
        <ApiKeysPanel />
        <PersonaManager />
        <DataIoPanel />
      </div>
    </PageShell>
  );
}

function ClaudeAuthPanel() {
  const [health, setHealth] = useState<ClaudeHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setHealth(await api.get<ClaudeHealth>("/health/claude"));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? `HTTP ${err.status}` : "Failed to load status.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function resetAuth() {
    if (
      !confirm(
        "Clear the stored Claude Code OAuth token? You'll need to run the login flow again on the Companion page.",
      )
    ) {
      return;
    }
    setResetting(true);
    setError(null);
    try {
      await api.delete("/api/v1/auth/claude-login/token");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? `Reset failed (HTTP ${err.status}).` : "Reset failed.");
    } finally {
      setResetting(false);
    }
  }

  return (
    <section className="jsp-card p-5">
      <header className="flex items-start justify-between gap-4 mb-3">
        <div>
          <h2 className="text-sm uppercase tracking-wider text-corp-muted">
            Claude Code Authentication
          </h2>
          <p className="text-xs text-corp-muted mt-1">
            The API container invokes <code>claude -p</code> as a subprocess. Auth is stored in an
            isolated config volume — your personal host auth is never touched.
          </p>
        </div>
        <button
          type="button"
          className="jsp-btn-ghost"
          onClick={refresh}
          disabled={loading}
          title="Re-check auth status"
        >
          {loading ? "..." : "Refresh"}
        </button>
      </header>

      {health ? (
        <div className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm mb-4">
          <div className="text-corp-muted">Status</div>
          <div>
            {health.authenticated ? (
              <span className="text-corp-ok">✓ Authenticated</span>
            ) : (
              <span className="text-corp-accent2">Not authenticated</span>
            )}
          </div>
          <div className="text-corp-muted">CLI available</div>
          <div>{health.claude_cli_available ? "yes" : "no"}</div>
          <div className="text-corp-muted">Method</div>
          <div>
            {health.has_oauth_session
              ? "Stored OAuth token"
              : health.has_anthropic_api_key
                ? "ANTHROPIC_API_KEY env var"
                : "None"}
          </div>
        </div>
      ) : loading ? (
        <div className="text-sm text-corp-muted mb-4">Loading...</div>
      ) : null}

      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
          onClick={resetAuth}
          disabled={resetting || !health?.has_oauth_session}
          title={
            health?.has_oauth_session
              ? "Remove the stored token"
              : "No stored token to clear"
          }
        >
          {resetting ? "Clearing..." : "Reset authentication"}
        </button>
        <Link href="/companion" className="jsp-btn-ghost">
          {health?.authenticated ? "Open Companion" : "Run login flow →"}
        </Link>
        {health?.has_anthropic_api_key ? (
          <span className="text-xs text-corp-muted">
            Resetting only clears the OAuth token; the API key env var still provides fallback auth.
          </span>
        ) : null}
      </div>

      {error ? (
        <div className="mt-3 text-sm text-corp-danger">{error}</div>
      ) : null}
    </section>
  );
}

// ---------- Persona manager -------------------------------------------------

type Persona = {
  id: number;
  name: string;
  description?: string | null;
  tone_descriptors?: string[] | null;
  system_prompt: string;
  avatar_url?: string | null;
  is_builtin: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

// ---------- API keys panel ---------------------------------------------------
//
// Per-user third-party API keys. Currently used by the Bright Data
// adapter (LinkedIn / Glassdoor scraping) but designed to host any
// provider. Secrets are stored AES-256-GCM-encrypted server-side; the
// list endpoint never returns the plaintext, only the last4 digits.

type Credential = {
  id: number;
  provider: string;
  label: string;
  last4: string;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};

const KNOWN_PROVIDERS: { value: string; label: string; hint: string }[] = [
  {
    value: "brightdata",
    label: "Bright Data",
    hint: (
      "Used by the Bright Data — LinkedIn / Glassdoor source kinds. " +
      "Find your key at brightdata.com → Account Settings → API tokens."
    ),
  },
];

function ApiKeysPanel() {
  const [items, setItems] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [provider, setProvider] = useState(KNOWN_PROVIDERS[0].value);
  const [label, setLabel] = useState("default");
  const [secret, setSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      const rows = await api.get<Credential[]>("/api/v1/auth/credentials");
      setItems(rows);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function save() {
    if (!secret.trim()) {
      setErr("Secret is required.");
      return;
    }
    setSaving(true);
    setErr(null);
    setSavedMsg(null);
    try {
      await api.put("/api/v1/auth/credentials", {
        provider,
        label: label.trim() || "default",
        secret: secret.trim(),
      });
      setSecret("");
      setSavedMsg(`${provider} key saved.`);
      await refresh();
      setTimeout(() => setSavedMsg(null), 2500);
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

  async function remove(id: number) {
    if (!confirm("Delete this API key?")) return;
    try {
      await api.delete(`/api/v1/auth/credentials/${id}`);
      await refresh();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Delete failed (HTTP ${e.status}).`
          : "Delete failed.",
      );
    }
  }

  const providerHint =
    KNOWN_PROVIDERS.find((p) => p.value === provider)?.hint ?? "";

  return (
    <section className="jsp-card p-5">
      <header className="mb-3">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted">
          Third-party API keys
        </h2>
        <p className="text-[11px] text-corp-muted mt-1">
          Stored AES-256-GCM-encrypted at rest. The plaintext is never
          returned by the list endpoint — only the last 4 characters
          for identification.
        </p>
      </header>

      {err ? (
        <div className="text-xs text-corp-danger mb-2">{err}</div>
      ) : null}
      {savedMsg ? (
        <div className="text-xs text-corp-muted mb-2">{savedMsg}</div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-[180px_180px_1fr_auto] gap-2 items-end mb-3">
        <div>
          <label className="jsp-label">Provider</label>
          <select
            className="jsp-input"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={saving}
          >
            {KNOWN_PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Label</label>
          <input
            className="jsp-input"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="default"
            disabled={saving}
          />
        </div>
        <div>
          <label className="jsp-label">Secret</label>
          <input
            type="password"
            className="jsp-input font-mono"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="paste your API key"
            disabled={saving}
            autoComplete="off"
          />
        </div>
        <div>
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={save}
            disabled={saving || !secret.trim()}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      {providerHint ? (
        <p className="text-[11px] text-corp-muted mb-3">{providerHint}</p>
      ) : null}

      {loading ? (
        <p className="text-sm text-corp-muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-corp-muted">
          No API keys saved. Add one above to enable paid sources like
          Bright Data.
        </p>
      ) : (
        <ul className="divide-y divide-corp-border">
          {items.map((c) => (
            <li
              key={c.id}
              className="py-2 flex items-center gap-3 text-sm"
            >
              <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border shrink-0">
                {c.provider}
              </span>
              <span className="text-corp-muted text-[11px] w-32 truncate">
                {c.label}
              </span>
              <span className="font-mono text-[11px] text-corp-muted">
                {c.last4}
              </span>
              <span className="text-[11px] text-corp-muted ml-auto">
                {c.last_used_at
                  ? `last used ${new Date(c.last_used_at).toLocaleString()}`
                  : "never used"}
              </span>
              <button
                type="button"
                className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                onClick={() => remove(c.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


function PersonaManager() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<Persona | "new" | null>(null);

  async function refresh() {
    setLoading(true);
    setErr(null);
    try {
      setPersonas(await api.get<Persona[]>("/api/v1/personas"));
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Failed to load personas.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function activate(id: number) {
    try {
      await api.post(`/api/v1/personas/${id}/activate`);
      await refresh();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Activation failed (HTTP ${e.status}).` : "Activation failed.",
      );
    }
  }

  async function deactivateAll() {
    try {
      await api.post("/api/v1/personas/deactivate");
      await refresh();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Deactivation failed (HTTP ${e.status}).`
          : "Deactivation failed.",
      );
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this persona? Cannot be undone.")) return;
    try {
      await api.delete(`/api/v1/personas/${id}`);
      await refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? `Delete failed (HTTP ${e.status}).` : "Delete failed.");
    }
  }

  const active = personas.find((p) => p.is_active) ?? null;

  return (
    <section className="jsp-card p-5">
      <header className="flex items-start justify-between gap-4 mb-3 flex-wrap">
        <div>
          <h2 className="text-sm uppercase tracking-wider text-corp-muted">AI Persona</h2>
          <p className="text-xs text-corp-muted mt-1">
            Preset tone and voice instructions that ride along with every Companion
            invocation. One persona can be active at a time.{" "}
            {active ? (
              <span className="text-corp-accent">Active: {active.name}.</span>
            ) : (
              <span>No persona is currently active.</span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          {active ? (
            <button className="jsp-btn-ghost" onClick={deactivateAll}>
              Deactivate all
            </button>
          ) : null}
          <button className="jsp-btn-primary" onClick={() => setEditing("new")}>
            + New persona
          </button>
        </div>
      </header>

      {err ? <div className="text-sm text-corp-danger mb-2">{err}</div> : null}

      {editing ? (
        <div className="jsp-card p-4 mb-3 bg-corp-surface2">
          <PersonaForm
            initial={editing === "new" ? null : editing}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              refresh();
            }}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-corp-muted">Loading...</p>
      ) : personas.length === 0 ? (
        <p className="text-sm text-corp-muted">
          No personas yet. Examples: Brisk Hiring Manager · Dry Analyst · Warm Mentor.
        </p>
      ) : (
        <ul className="divide-y divide-corp-border">
          {personas.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-3 py-2 first:pt-0 last:pb-0"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="text-sm font-medium">{p.name}</span>
                  {p.is_active ? (
                    <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-accent/25 text-corp-accent border border-corp-accent/40">
                      active
                    </span>
                  ) : null}
                  {p.tone_descriptors && p.tone_descriptors.length > 0 ? (
                    <span className="text-[11px] text-corp-muted">
                      · {p.tone_descriptors.join(", ")}
                    </span>
                  ) : null}
                </div>
                {p.description ? (
                  <div className="text-[11px] text-corp-muted truncate">
                    {p.description}
                  </div>
                ) : null}
              </div>
              <div className="flex gap-1 shrink-0">
                {!p.is_active ? (
                  <button
                    className="jsp-btn-ghost text-xs"
                    onClick={() => activate(p.id)}
                  >
                    Activate
                  </button>
                ) : null}
                <button
                  className="jsp-btn-ghost text-xs"
                  onClick={() => setEditing(p)}
                >
                  Edit
                </button>
                <button
                  className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                  onClick={() => remove(p.id)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PersonaForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial: Persona | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [tonesText, setTonesText] = useState(
    (initial?.tone_descriptors ?? []).join(", "),
  );
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setErr("Name is required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const tones = tonesText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const payload = {
        name: name.trim(),
        description: description.trim() || null,
        tone_descriptors: tones.length ? tones : null,
        system_prompt: systemPrompt,
      };
      if (initial) {
        await api.put(`/api/v1/personas/${initial.id}`, payload);
      } else {
        await api.post("/api/v1/personas", payload);
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Name</label>
          <input
            className="jsp-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Dry Analyst"
          />
        </div>
        <div>
          <label className="jsp-label">Tone descriptors (comma-separated)</label>
          <input
            className="jsp-input"
            value={tonesText}
            onChange={(e) => setTonesText(e.target.value)}
            placeholder="precise, terse, skeptical"
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Description (optional)</label>
          <input
            className="jsp-input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Short summary for this persona's style."
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Custom instructions</label>
          <textarea
            className="jsp-input min-h-[140px] font-mono text-sm"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Additional rules for the Companion while this persona is active. E.g. 'Never use exclamation marks. Prefer Latin-root verbs. Flag hype language in the user's drafts.'"
          />
        </div>
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "Saving..." : initial ? "Save" : "Create"}
        </button>
      </div>
    </form>
  );
}

function DataIoPanel() {
  const [importing, setImporting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function doExport() {
    setErr(null);
    try {
      const res = await fetch(apiUrl("/api/v1/admin/export"), {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const ts = new Date().toISOString().replace(/[:T]/g, "-").slice(0, 19);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `jsp-export-${ts}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
      setMsg("Export downloaded.");
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Export failed.");
    }
  }

  async function doImport(file: File) {
    if (!confirm(
      "Import rows from this file? Existing data is kept; new rows will be added alongside it.",
    )) return;
    setImporting(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(apiUrl("/api/v1/admin/import"), {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
      const r = (await res.json()) as { imported: Record<string, number> };
      const total = Object.values(r.imported).reduce((a, b) => a + b, 0);
      setMsg(`Imported ${total} rows across ${Object.keys(r.imported).length} tables.`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <section className="jsp-card p-5">
      <h2 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
        Data Export / Import
      </h2>
      <p className="text-xs text-corp-muted mb-3">
        Full JSON dump of everything you own — jobs, history, documents, personas,
        preferences, chat transcripts. Import re-inserts rows with fresh ids;
        nothing is overwritten.
      </p>
      <div className="flex flex-wrap gap-2 items-center">
        <button type="button" className="jsp-btn-primary" onClick={doExport}>
          Export JSON
        </button>
        <label
          className={`jsp-btn-ghost cursor-pointer inline-flex ${
            importing ? "opacity-50 pointer-events-none" : ""
          }`}
        >
          {importing ? "Importing..." : "Import JSON..."}
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) doImport(f);
            }}
          />
        </label>
        {msg ? <span className="text-xs text-corp-muted">{msg}</span> : null}
        {err ? <span className="text-xs text-corp-danger">{err}</span> : null}
      </div>
    </section>
  );
}
