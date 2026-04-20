import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";

export default function PreferencesPage() {
  return (
    <PageShell
      title="Preferences & Identity"
      subtitle="What you want in a job, what you're authorized to do, and voluntary self-identification."
    >
      <div className="space-y-4">
        <ComingSoon
          title="Job Preferences"
          description="Three-tier criteria (preferred, acceptable, unacceptable) for salary, experience level, remote policy, commute, travel, hours, schedule, employment type, equity, benefits, industry, role, technology, company size/type, mission area, and more."
          plannedFor="R5"
        />
        <ComingSoon
          title="Work Authorization"
          description="Citizenship, visa status, sponsorship requirements now and future, relocation willingness, security clearance, export-control considerations."
          plannedFor="R5"
        />
        <ComingSoon
          title="Demographics (Voluntary Self-Identification)"
          description="EEOC-style optional fields with independent per-field share policies. Never transmitted to the LLM as free text — templated placeholders only."
          plannedFor="R5"
        />
      </div>
    </PageShell>
  );
}
