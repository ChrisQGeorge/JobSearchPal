import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";

export default function SamplesPage() {
  return (
    <PageShell
      title="Writing Samples Library"
      subtitle="Upload your own writing so AI output can be rewritten in your voice."
    >
      <ComingSoon
        title="Writing Samples Library"
        description="Drag-and-drop upload of txt, md, pdf, docx. Per-sample tagging and a paste-in quick entry. Samples are the reference corpus for the humanizer skill."
        plannedFor="R4"
      />
    </PageShell>
  );
}
