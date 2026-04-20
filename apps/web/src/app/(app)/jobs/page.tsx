import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";

export default function JobTrackerPage() {
  return (
    <PageShell
      title="Job Tracker"
      subtitle="Applied, watched, won, lost — every opportunity tracked through its full lifecycle."
    >
      <ComingSoon
        title="Job Tracker"
        description="Sort and filter applied/watched jobs across the full status vocabulary (watching, interested, applied, responded, screening, interviewing, assessment, offer, won, lost, withdrawn, ghosted, archived). Interview rounds and artifacts will live under Job Detail."
        plannedFor="R2"
      />
    </PageShell>
  );
}
