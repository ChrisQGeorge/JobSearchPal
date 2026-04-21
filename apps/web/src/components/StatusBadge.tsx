import type { JobStatus } from "@/lib/types";

// Status visual style for TrackedJob.status. One palette entry per status.
const STATUS_STYLES: Record<JobStatus, string> = {
  watching: "bg-corp-surface2 text-corp-muted border-corp-border",
  interested: "bg-sky-500/20 text-sky-300 border-sky-500/40",
  applied: "bg-corp-accent/25 text-corp-accent border-corp-accent/40",
  responded: "bg-sky-500/25 text-sky-200 border-sky-500/50",
  screening: "bg-violet-500/25 text-violet-300 border-violet-500/40",
  interviewing: "bg-violet-500/30 text-violet-200 border-violet-500/50",
  assessment: "bg-pink-500/25 text-pink-300 border-pink-500/40",
  offer: "bg-emerald-500/25 text-emerald-300 border-emerald-500/50",
  won: "bg-emerald-500/40 text-emerald-200 border-emerald-400",
  lost: "bg-corp-danger/20 text-corp-danger border-corp-danger/40",
  withdrawn: "bg-corp-surface2 text-corp-muted border-corp-border",
  ghosted: "bg-corp-muted/20 text-corp-muted border-corp-muted/40",
  archived: "bg-corp-surface2 text-corp-muted border-corp-border",
};

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider border ${STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  );
}

export { STATUS_STYLES };
