"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";
import type { TimelineEvent } from "@/lib/types";

const KIND_COLORS: Record<TimelineEvent["kind"], string> = {
  work: "border-corp-accent",
  education: "border-sky-400",
  course: "border-sky-300",
  certification: "border-emerald-400",
  project: "border-violet-400",
  publication: "border-rose-400",
  presentation: "border-pink-400",
  achievement: "border-corp-accent2",
  volunteer: "border-teal-400",
  custom: "border-corp-border",
};

export default function TimelinePage() {
  const router = useRouter();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<TimelineEvent[]>("/api/v1/history/timeline")
      .then((ev) => {
        setEvents(ev);
        setLoading(false);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        } else {
          setLoading(false);
        }
      });
  }, [router]);

  return (
    <PageShell
      title="Career Timeline"
      subtitle="A chronological record of every dated event — for your reassurance and the Companion's reference."
    >
      {loading ? (
        <p className="text-corp-muted">Retrieving chronology...</p>
      ) : events.length === 0 ? (
        <div className="jsp-card p-6 text-corp-muted text-sm">
          No events recorded yet. Add entries on the{" "}
          <a href="/history" className="text-corp-accent hover:underline">History Editor</a>.
        </div>
      ) : (
        <ol className="relative border-l border-corp-border pl-6 space-y-4">
          {events.map((ev) => (
            <li
              key={`${ev.kind}-${ev.id}`}
              className={`jsp-card p-4 border-l-4 ${KIND_COLORS[ev.kind]}`}
            >
              <div className="flex items-baseline justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-wider text-corp-muted">
                    {ev.kind}
                  </div>
                  <div className="text-base font-medium">{ev.title}</div>
                  {ev.subtitle ? (
                    <div className="text-sm text-corp-muted">{ev.subtitle}</div>
                  ) : null}
                </div>
                <div className="text-xs text-corp-muted text-right shrink-0">
                  {ev.start_date ?? "—"} → {ev.end_date ?? "current"}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </PageShell>
  );
}
