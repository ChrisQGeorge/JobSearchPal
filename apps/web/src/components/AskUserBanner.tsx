"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

type ApplicationRunOut = {
  id: number;
  tracked_job_id: number;
  state: string;
  pending_question?: string | null;
  updated_at: string;
};

const POLL_MS = 15_000;

/**
 * Sticky banner that watches for ApplicationRun rows in state=awaiting_user
 * and surfaces them across the app. Polls every 15s and fires a desktop
 * Web Notification on the rising edge of any new pending question, so the
 * user gets pinged even when the tab isn't focused. Notifications require
 * user permission — we ask once when the banner first sees a pause.
 */
export function AskUserBanner() {
  const [runs, setRuns] = useState<ApplicationRunOut[]>([]);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const knownIds = useRef<Set<number>>(new Set());

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const list = await api.get<ApplicationRunOut[]>(
          "/api/v1/application-runs?state=awaiting_user&limit=20",
        );
        if (cancelled) return;
        setRuns(list);
        // Fire desktop notifications for any newly-pending runs.
        const seen = knownIds.current;
        const newPauses = list.filter((r) => !seen.has(r.id));
        for (const r of newPauses) seen.add(r.id);
        if (newPauses.length > 0) {
          maybeNotify(newPauses);
        }
      } catch (err) {
        // 401 means the session expired — let the rest of the app
        // handle redirecting; we just stop polling silently.
        if (err instanceof ApiError && err.status === 401) {
          cancelled = true;
        }
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const visible = runs.filter((r) => !dismissed.has(r.id));
  if (visible.length === 0) return null;

  return (
    <div className="sticky top-0 z-20 border-b border-corp-accent2 bg-corp-accent2/10 backdrop-blur">
      <div className="px-6 py-2 flex items-start justify-between gap-4">
        <div className="text-sm">
          <span className="font-semibold text-corp-accent2 mr-2">
            {visible.length === 1
              ? "The Companion needs your input"
              : `${visible.length} runs await your input`}
          </span>
          {visible.length === 1 ? (
            <span className="text-corp-muted">
              {truncate(visible[0].pending_question ?? "Pending question.", 240)}
            </span>
          ) : null}
        </div>
        <div className="flex gap-2 shrink-0">
          <Link
            href={`/applications?focus=${visible[0].id}`}
            className="jsp-btn-ghost text-xs"
          >
            Open
          </Link>
          <button
            type="button"
            className="jsp-btn-ghost text-xs"
            onClick={() => {
              setDismissed((d) => {
                const next = new Set(d);
                for (const r of visible) next.add(r.id);
                return next;
              });
            }}
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

let _permissionAsked = false;
function maybeNotify(runs: ApplicationRunOut[]) {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  const fire = () => {
    for (const r of runs) {
      try {
        const n = new Notification("Job Search Pal — input needed", {
          body: r.pending_question ?? "An apply_run is paused awaiting your input.",
          tag: `apply-run-${r.id}`,
          requireInteraction: false,
        });
        n.onclick = () => {
          window.focus();
          window.location.href = `/applications?focus=${r.id}`;
          n.close();
        };
      } catch {
        // Some browsers throw when the page hasn't been interacted with;
        // ignore and rely on the in-page banner.
      }
    }
  };
  if (Notification.permission === "granted") {
    fire();
  } else if (Notification.permission !== "denied" && !_permissionAsked) {
    _permissionAsked = true;
    Notification.requestPermission().then((p) => {
      if (p === "granted") fire();
    });
  }
}
