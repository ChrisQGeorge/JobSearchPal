"use client";

// Wraps the authenticated app layout. Probes /health on mount; if the
// backend isn't responding (which is the normal state for ~15-30s
// after `docker compose up` while MySQL warms and alembic migrates),
// shows a full-screen loading overlay and keeps polling. When the
// backend comes back, hides the overlay and pushes the user to the
// dashboard so they land on a known-good page rather than a partly-
// loaded one they happened to be on when the outage hit.

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

const POLL_HEALTHY_MS = 30_000;   // background heartbeat
const POLL_UNHEALTHY_MS = 2_000;  // recovery polling

export function HealthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [available, setAvailable] = useState(true);
  const [downSince, setDownSince] = useState<Date | null>(null);
  // Track outage state across renders without re-triggering the effect.
  const wasDownRef = useRef(false);
  const pathRef = useRef(pathname);
  pathRef.current = pathname;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function probe() {
      try {
        const res = await fetch("/health", { cache: "no-store" });
        if (cancelled) return;
        if (res.ok) {
          setAvailable(true);
          setDownSince(null);
          if (wasDownRef.current) {
            // Recovered. Redirect to dashboard, but only if the user
            // isn't already there — avoids a no-op navigation.
            wasDownRef.current = false;
            if (pathRef.current !== "/") {
              router.push("/");
            }
          }
          timer = setTimeout(probe, POLL_HEALTHY_MS);
          return;
        }
        throw new Error(`status ${res.status}`);
      } catch {
        if (cancelled) return;
        setAvailable(false);
        if (!wasDownRef.current) {
          wasDownRef.current = true;
          setDownSince(new Date());
        }
        timer = setTimeout(probe, POLL_UNHEALTHY_MS);
      }
    }

    probe();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [router]);

  return (
    <>
      {children}
      {!available ? <LoadingOverlay downSince={downSince} /> : null}
    </>
  );
}

function LoadingOverlay({ downSince }: { downSince: Date | null }) {
  // Tick a second-resolution clock so the "for Ns" counter updates
  // visibly while the user waits. Cheap — only mounts when overlay is
  // showing.
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
        {/* Soft pulse, no spinner — matches the corp-aesthetic better. */}
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
