import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";

export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <PageShell title={`Job #${id}`} subtitle="Full detail view with rounds, artifacts, and generated docs.">
      <ComingSoon
        title="Job Detail"
        description="Tabs for Overview, Interview Rounds, Interview Artifacts, Contacts, Documents, and Activity. Inline action buttons to generate tailored resumes, cover letters, emails, and run JD analysis."
        plannedFor="R2"
      />
    </PageShell>
  );
}
