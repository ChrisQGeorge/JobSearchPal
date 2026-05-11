"use client";

// Streamed Chromium control surface (R10).
//
// The api container reverse-proxies the chromium service's KasmVNC
// session over a WebSocket at /api/v1/browser/stream, gated by cookie
// auth. The simplest way to render that in the browser is to load the
// chromium service's web app directly via an iframe in dev — KasmVNC
// ships its own UI. For self-host we'd ideally embed via a custom
// noVNC client to avoid the iframe round-trip, but iframe-to-LAN is
// fine for a single-user deployment and keeps this page small.
//
// We DO NOT expose the chromium container's host port. The user's
// browser hits the api host, the api proxies through the docker
// network to chromium. That keeps cookie auth in front of every
// connection and means there's only one port mapped on the host.

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

type BrowserInfo = {
  cdp_reachable: boolean;
  vnc_reachable: boolean;
  driver: string;
  chromium_host: string;
  note?: string | null;
};

export default function BrowserPage() {
  const [info, setInfo] = useState<BrowserInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [navUrl, setNavUrl] = useState("");
  const [navigating, setNavigating] = useState(false);
  const [navMsg, setNavMsg] = useState<string | null>(null);

  async function refresh() {
    try {
      const i = await api.get<BrowserInfo>("/api/v1/browser/info");
      setInfo(i);
      setErr(null);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Status check failed (HTTP ${e.status}).`
          : "Status check failed.",
      );
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, []);

  async function navigate() {
    if (!navUrl.trim()) return;
    setNavigating(true);
    setNavMsg(null);
    try {
      const out = await api.post<{ url: string; title: string }>(
        "/api/v1/browser/navigate",
        { url: navUrl.trim() },
      );
      setNavMsg(`Loaded: ${out.title || out.url}`);
    } catch (e) {
      setNavMsg(
        e instanceof ApiError
          ? `Navigate failed (HTTP ${e.status}).`
          : "Navigate failed.",
      );
    } finally {
      setNavigating(false);
    }
  }

  async function setDriver(who: "user" | "companion") {
    const path =
      who === "user" ? "/api/v1/browser/take-over" : "/api/v1/browser/release";
    try {
      await api.post(path, {});
      await refresh();
    } catch {
      /* non-fatal */
    }
  }

  // Build the iframe target URL for the streamed chromium container.
  //
  // Three sources, in priority order:
  //   1. NEXT_PUBLIC_CHROMIUM_URL — explicit override for users
  //      fronting the stack with a reverse proxy that doesn't fit
  //      the heuristics below.
  //   2. If the current page is loaded over HTTPS (i.e. behind
  //      Caddy), point at the HTTPS chromium port (default 6443).
  //      Mixed-content rules block iframing HTTP into an HTTPS
  //      page, so we MUST stay on HTTPS in this branch.
  //   3. Otherwise (plain HTTP / localhost dev), use the plain
  //      CHROMIUM_PORT (default 6901).
  // KasmVNC defaults to single-primary-client mode — opening the
  // /browser page in a second tab kicks the first one with a
  // "Connection Terminated: a new primary client connected" toast.
  // Append ?shared=1 to the iframe URL so multiple viewers can
  // attach simultaneously (e.g., the user has the page open on
  // both a laptop and a phone, or accidentally double-clicked).
  const [streamUrl, setStreamUrl] = useState<string>("");
  useEffect(() => {
    const append = (u: string) =>
      u.includes("?") ? `${u}&shared=1` : `${u}/?shared=1`;
    const fromEnv = process.env.NEXT_PUBLIC_CHROMIUM_URL;
    if (fromEnv) {
      setStreamUrl(append(fromEnv));
      return;
    }
    if (typeof window !== "undefined") {
      const isHttps = window.location.protocol === "https:";
      const port = isHttps
        ? process.env.NEXT_PUBLIC_HTTPS_CHROMIUM_PORT || "6443"
        : process.env.NEXT_PUBLIC_CHROMIUM_PORT || "6901";
      setStreamUrl(
        append(
          `${window.location.protocol}//${window.location.hostname}:${port}`,
        ),
      );
    }
  }, []);

  const reachable = info?.cdp_reachable && info?.vnc_reachable;

  return (
    <PageShell
      title="Streamed Browser"
      subtitle="Shared Chromium session — both you and the Companion drive it. Persistent profile keeps logins across restarts."
    >
      {err ? (
        <div className="jsp-card p-4 text-sm text-corp-danger mb-3">{err}</div>
      ) : null}

      {info && !reachable ? (
        <div className="jsp-card p-4 text-sm text-corp-accent2 mb-3 space-y-1">
          <div>
            Chromium service isn&apos;t reachable yet. CDP={String(info.cdp_reachable)} ·
            VNC={String(info.vnc_reachable)}.
          </div>
          {info.note ? <div className="text-corp-muted">{info.note}</div> : null}
          <div className="text-corp-muted">
            Run <code>docker compose up -d chromium</code> on the host. First
            boot takes ~30 s.
          </div>
        </div>
      ) : null}

      <div className="jsp-card p-3 mb-3 flex flex-wrap gap-2 items-end">
        <div className="flex-1 min-w-[16rem]">
          <label className="jsp-label">Navigate to URL</label>
          <input
            className="jsp-input"
            value={navUrl}
            onChange={(e) => setNavUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") navigate();
            }}
            placeholder="https://boards.greenhouse.io/anthropic"
            disabled={navigating || !reachable}
          />
        </div>
        <button
          className="jsp-btn-primary"
          onClick={navigate}
          disabled={navigating || !reachable || !navUrl.trim()}
        >
          {navigating ? "Loading…" : "Open"}
        </button>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-corp-muted">
            Driver: <b>{info?.driver ?? "—"}</b>
          </span>
          <button
            className={`jsp-btn-ghost text-xs ${
              info?.driver === "user" ? "border-corp-accent text-corp-accent" : ""
            }`}
            onClick={() => setDriver("user")}
            disabled={!reachable}
            title="I'll drive — Companion stand down. (Both still work; this is a UI hint, not a hard lock.)"
          >
            I&apos;m driving
          </button>
          <button
            className={`jsp-btn-ghost text-xs ${
              info?.driver === "companion" ? "border-corp-accent text-corp-accent" : ""
            }`}
            onClick={() => setDriver("companion")}
            disabled={!reachable}
            title="Hand the wheel back to the Companion."
          >
            Companion drives
          </button>
        </div>
      </div>

      {navMsg ? (
        <div className="text-[11px] text-corp-muted mb-2">{navMsg}</div>
      ) : null}

      <div className="jsp-card overflow-hidden" style={{ minHeight: "70vh" }}>
        {reachable ? (
          <iframe
            src={streamUrl}
            title="Streamed Chromium"
            className="w-full"
            style={{ height: "78vh", border: 0 }}
            // The chromium container serves https-style WebSocket
            // upgrades inside the iframe. Allow whatever it wants.
            allow="clipboard-read; clipboard-write; fullscreen"
          />
        ) : (
          <div className="p-8 text-center text-corp-muted">
            Browser stream unavailable.
          </div>
        )}
      </div>

      <p className="text-[11px] text-corp-muted mt-3">
        See <Link href="/applications" className="text-corp-accent">/applications</Link>{" "}
        to start an Companion-driven application run, or{" "}
        <Link href="/answers" className="text-corp-accent">/answers</Link> to
        manage saved form answers.
      </p>
    </PageShell>
  );
}
