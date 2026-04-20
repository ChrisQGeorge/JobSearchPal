import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";

export default function CompanionPage() {
  return (
    <PageShell
      title="Companion"
      subtitle="Your loyal and only mildly ironic corporate career assistant."
    >
      <ComingSoon
        title="Companion Chat"
        description="Persistent conversations with Claude Code — skill invocations visible inline, messages pinnable, and every conversation can be attached to a TrackedJob."
        plannedFor="R3"
      />
    </PageShell>
  );
}
