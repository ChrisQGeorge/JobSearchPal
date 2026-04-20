import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";

export default function StudioPage() {
  return (
    <PageShell
      title="Document Studio"
      subtitle="Generate and iterate on tailored resumes, CVs, cover letters, and emails."
    >
      <ComingSoon
        title="Document Studio"
        description="Side-by-side source history and generated output, with regenerate, humanize, and selection-to-Companion rewrite controls. Version history and diffs included."
        plannedFor="R4"
      />
    </PageShell>
  );
}
