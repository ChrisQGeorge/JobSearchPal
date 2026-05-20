"use client";

// Wraps the authenticated app layout. Probes the backend once on
// mount. If it answers cleanly → render children immediately and
// never check again for the rest of the session. If it doesn't →
// render children with a full-screen loading overlay on top, and
// keep polling until the first success, at which point the overlay
// disappears, the user gets redirected to /, and the gate goes
// dormant permanently.
//
// We intentionally do NOT poll on a heartbeat after the first
// successful probe. The original design did (30s interval) so the
// overlay would reappear if the backend died mid-session — but in
// practice that caused flicker during transient slow requests
// (Companion turns holding the proxy, etc.), which is much worse
// than the rare "backend genuinely died" case.

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

const POLL_UNHEALTHY_MS = 2_000;

export function HealthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [overlayActive, setOverlayActive] = useState(false);
  const [downSince, setDownSince] = useState<Date | null>(null);
  // Once the backend confirms ready ONCE, this stays true for the
  // life of the page. Probe loop short-circuits on every iteration
  // and the overlay can never re-appear, no matter what transient
  // failures the rest of the session produces.
  const readyRef = useRef(false);
  const pathRef = useRef(pathname);
  pathRef.current = pathname;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function probe() {
      if (readyRef.current) return; // already dismissed; never re-check
      try {
        // 1) Basic connectivity + SELECT 1 via /health.
        const healthRes = await fetch("/health", { cache: "no-store" });
        if (cancelled) return;
        if (!healthRes.ok) throw new Error(`/health ${healthRes.status}`);

        // 2) Exercise the auth + ORM model-load chain the dashboard
        //    uses on mount. 401 is fine — that just means no session,
        //    not that the api is broken.
        const dataRes = await fetch("/api/v1/auth/me", { cache: "no-store" });
        if (cancelled) return;
        if (dataRes.status >= 500) {
          throw new Error(`/api/v1/auth/me ${dataRes.status}`);
        }

        // Both probes passed → ready for good.
        readyRef.current = true;
        setOverlayActive(false);
        setDownSince(null);
        // If we ever showed the overlay (recovered from a downtime),
        // bounce to the dashboard so the user lands on a known-good
        // page rather than whichever URL they happened to be on.
        if (downSince !== null && pathRef.current !== "/") {
          router.push("/");
        }
      } catch {
        if (cancelled || readyRef.current) return;
        // Only show overlay on FAILURE before we've confirmed ready
        // once. After confirmation we never enter this branch (the
        // guard at the top of probe() short-circuits).
        setOverlayActive(true);
        if (downSince === null) setDownSince(new Date());
        timer = setTimeout(probe, POLL_UNHEALTHY_MS);
      }
    }

    probe();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // Intentionally empty deps — we want a single probe loop per
    // page life, not one that restarts on every router change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      {children}
      {overlayActive ? <LoadingOverlay downSince={downSince} /> : null}
    </>
  );
}

function LoadingOverlay({ downSince }: { downSince: Date | null }) {
  // Tick a second-resolution clock so the "for Ns" counter updates
  // visibly while the user waits. Cheap — only mounts when overlay
  // is showing.
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1_000);
    return () => clearInterval(id);
  }, []);

  const seconds = downSince
    ? Math.max(0, Math.round((Date.now() - downSince.getTime()) / 1000))
    : 0;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-50 flex items-center justify-center bg-corp-bg/95 backdrop-blur-sm"
    >
      <div className="jsp-card p-6 max-w-sm w-full mx-4 text-center space-y-3">
        <div className="text-corp-accent uppercase tracking-wider text-xs">
          Job Search Pal · Initializing
        </div>
        <div className="text-corp-text text-base">
          Bringing the back office online…
        </div>
        <div className="text-corp-muted text-xs">
          Waiting for the database and API to come up. You&apos;ll be
          dropped on the dashboard the moment they&apos;re ready.
        </div>
        <div className="text-corp-muted text-[10px] uppercase tracking-wider">
          {seconds > 0 ? `Offline for ${seconds}s` : "Probing…"}
        </div>
        <div className="flex justify-center gap-1.5 pt-1">
          <span className="w-1.5 h-1.5 rounded-full bg-corp-accent animate-pulse" />
          <span
            className="w-1.5 h-1.5 rounded-full bg-corp-accent animate-pulse"
            style={{ animationDelay: "150ms" }}
          />
          <span
            className="w-1.5 h-1.5 rounded-full bg-corp-accent animate-pulse"
            style={{ animationDelay: "300ms" }}
          />
        </div>
      </div>
    </div>
  );
}
