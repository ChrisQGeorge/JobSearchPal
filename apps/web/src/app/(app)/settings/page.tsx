"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";
import { api, ApiError } from "@/lib/api";

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
        <ComingSoon
          title="AI Persona"
          description="Pick from built-in personas or define custom ones with name, tone descriptors, system prompt, and avatar."
          plannedFor="R5"
        />
        <ComingSoon
          title="Data Export / Reset"
          description="JSON + SQL dump export. Credential rotation. Full data purge."
          plannedFor="R0+"
        />
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
