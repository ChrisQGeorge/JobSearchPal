"use client";

import { useState } from "react";
import { PageShell } from "@/components/PageShell";
import { EducationPanel } from "./_panels/EducationPanel";
import { WorkPanel } from "./_panels/WorkPanel";
import { GenericEntityPanel } from "./_panels/shared";
import type {
  Achievement,
  Certification,
  Contact,
  CustomEvent,
  Language,
  Presentation,
  Project,
  Publication,
  Skill,
  VolunteerWork,
} from "@/lib/types";

type Tab =
  | "work"
  | "education"
  | "skills"
  | "certifications"
  | "projects"
  | "publications"
  | "presentations"
  | "achievements"
  | "volunteer"
  | "languages"
  | "contacts"
  | "custom";

const TABS: { key: Tab; label: string }[] = [
  { key: "work", label: "Work" },
  { key: "education", label: "Education" },
  { key: "skills", label: "Skills" },
  { key: "certifications", label: "Certifications" },
  { key: "projects", label: "Projects" },
  { key: "publications", label: "Publications" },
  { key: "presentations", label: "Presentations" },
  { key: "achievements", label: "Achievements" },
  { key: "volunteer", label: "Volunteer" },
  { key: "languages", label: "Languages" },
  { key: "contacts", label: "Contacts" },
  { key: "custom", label: "Custom Events" },
];

export default function HistoryEditorPage() {
  const [tab, setTab] = useState<Tab>("work");
  return (
    <PageShell
      title="History Editor"
      subtitle="Your canonical career record. Every AI skill draws from what is recorded here — and nothing else."
    >
      <div className="flex gap-1 mb-4 border-b border-corp-border overflow-x-auto whitespace-nowrap">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-2 text-sm transition-colors ${
              tab === t.key
                ? "text-corp-accent border-b-2 border-corp-accent"
                : "text-corp-muted hover:text-corp-text"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "work" && <WorkPanel />}
      {tab === "education" && <EducationPanel />}
      {tab === "skills" && (
        <GenericEntityPanel<Skill>
          endpoint="/api/v1/history/skills"
          title="Skills Catalog"
          entityType="skill"
          labelOf={(s) => s.name}
          subtitleOf={(s) =>
            [s.category, s.proficiency, s.years_experience && `${s.years_experience} yrs`]
              .filter(Boolean)
              .join(" · ") || null
          }
          emptyHint="Skills you add to Work or Courses also appear here. This is the canonical catalog."
          fields={[
            { key: "name", label: "Name", kind: "text", required: true },
            {
              key: "category",
              label: "Category",
              kind: "select",
              options: ["technical", "soft", "domain", "tool", "language"],
            },
            {
              key: "proficiency",
              label: "Proficiency",
              kind: "select",
              options: ["novice", "intermediate", "advanced", "expert"],
            },
            { key: "years_experience", label: "Years experience", kind: "number" },
            { key: "last_used_date", label: "Last used", kind: "date" },
            { key: "evidence_notes", label: "Evidence notes", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
      {tab === "achievements" && (
        <GenericEntityPanel<Achievement>
          endpoint="/api/v1/history/achievements"
          title="Achievements"
          entityType="achievement"
          emptyHint="No achievements recorded. Modesty is not a competitive advantage."
          labelOf={(a) => a.title}
          subtitleOf={(a) =>
            [a.issuer, a.date_awarded].filter(Boolean).join(" · ") || null
          }
          fields={[
            { key: "title", label: "Title", kind: "text", required: true, fullWidth: true },
            { key: "issuer", label: "Issuer", kind: "text" },
            { key: "type", label: "Type", kind: "text", placeholder: "award / scholarship / patent / ..." },
            { key: "date_awarded", label: "Date awarded", kind: "date" },
            { key: "url", label: "URL", kind: "url" },
            { key: "supporting_document_url", label: "Supporting document URL", kind: "url" },
            { key: "description", label: "Description", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
      {tab === "certifications" && (
        <GenericEntityPanel<Certification>
          endpoint="/api/v1/history/certifications"
          title="Certifications"
          entityType="certification"
          labelOf={(c) => c.name}
          subtitleOf={(c) =>
            [c.issuer, c.issued_date].filter(Boolean).join(" · ") || null
          }
          fields={[
            { key: "name", label: "Name", kind: "text", required: true, fullWidth: true },
            { key: "issuer", label: "Issuer", kind: "text" },
            { key: "verification_status", label: "Verification status", kind: "text" },
            { key: "issued_date", label: "Issued", kind: "date" },
            { key: "expires_date", label: "Expires", kind: "date" },
            { key: "credential_id", label: "Credential ID", kind: "text" },
            { key: "credential_url", label: "Credential URL", kind: "url", fullWidth: true },
          ]}
        />
      )}
      {tab === "projects" && (
        <GenericEntityPanel<Project>
          endpoint="/api/v1/history/projects"
          title="Projects"
          entityType="project"
          labelOf={(p) => p.name}
          subtitleOf={(p) =>
            [p.role, p.start_date, p.end_date ?? (p.is_ongoing ? "present" : "")]
              .filter(Boolean)
              .join(" · ") || null
          }
          fields={[
            { key: "name", label: "Name", kind: "text", required: true, fullWidth: true },
            { key: "role", label: "Role", kind: "text" },
            {
              key: "visibility",
              label: "Visibility",
              kind: "select",
              options: ["private", "public", "portfolio_only"],
            },
            { key: "url", label: "URL", kind: "url" },
            { key: "repo_url", label: "Repo URL", kind: "url" },
            { key: "start_date", label: "Start date", kind: "date" },
            { key: "end_date", label: "End date", kind: "date" },
            { key: "summary", label: "Summary", kind: "textarea", fullWidth: true },
            {
              key: "technologies_used",
              label: "Technologies (comma-separated)",
              kind: "csv",
              fullWidth: true,
            },
            { key: "description_md", label: "Description", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
      {tab === "publications" && (
        <GenericEntityPanel<Publication>
          endpoint="/api/v1/history/publications"
          title="Publications"
          entityType="publication"
          labelOf={(p) => p.title}
          subtitleOf={(p) =>
            [p.venue, p.publication_date].filter(Boolean).join(" · ") || null
          }
          fields={[
            { key: "title", label: "Title", kind: "text", required: true, fullWidth: true },
            {
              key: "type",
              label: "Type",
              kind: "select",
              options: [
                "journal_article",
                "conference_paper",
                "book",
                "book_chapter",
                "blog_post",
                "whitepaper",
                "other",
              ],
            },
            { key: "venue", label: "Venue", kind: "text" },
            { key: "publication_date", label: "Publication date", kind: "date" },
            { key: "doi", label: "DOI", kind: "text" },
            { key: "url", label: "URL", kind: "url" },
            { key: "citation_count", label: "Citation count", kind: "number" },
            { key: "authors", label: "Authors (comma-separated)", kind: "csv", fullWidth: true },
            { key: "abstract", label: "Abstract", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
      {tab === "presentations" && (
        <GenericEntityPanel<Presentation>
          endpoint="/api/v1/history/presentations"
          title="Presentations"
          entityType="presentation"
          labelOf={(p) => p.title}
          subtitleOf={(p) =>
            [p.venue, p.event_name, p.date_presented].filter(Boolean).join(" · ") || null
          }
          fields={[
            { key: "title", label: "Title", kind: "text", required: true, fullWidth: true },
            {
              key: "format",
              label: "Format",
              kind: "select",
              options: ["talk", "workshop", "panel", "poster"],
            },
            { key: "venue", label: "Venue", kind: "text" },
            { key: "event_name", label: "Event", kind: "text" },
            { key: "date_presented", label: "Date", kind: "date" },
            { key: "audience_size", label: "Audience size", kind: "number" },
            { key: "slides_url", label: "Slides URL", kind: "url" },
            { key: "recording_url", label: "Recording URL", kind: "url" },
            { key: "summary", label: "Summary", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
      {tab === "volunteer" && (
        <GenericEntityPanel<VolunteerWork>
          endpoint="/api/v1/history/volunteer"
          title="Volunteer Work"
          entityType="volunteer"
          labelOf={(v) => v.role || v.organization}
          subtitleOf={(v) =>
            [v.organization, v.start_date, v.end_date ?? "present"]
              .filter(Boolean)
              .join(" · ") || null
          }
          fields={[
            {
              key: "organization",
              label: "Organization",
              kind: "text",
              required: true,
              fullWidth: true,
            },
            { key: "role", label: "Role", kind: "text" },
            { key: "cause_area", label: "Cause area", kind: "text" },
            { key: "start_date", label: "Start date", kind: "date" },
            { key: "end_date", label: "End date", kind: "date" },
            { key: "hours_total", label: "Total hours", kind: "number" },
            { key: "summary", label: "Summary", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
      {tab === "languages" && (
        <GenericEntityPanel<Language>
          endpoint="/api/v1/history/languages"
          title="Languages"
          entityType="language"
          labelOf={(l) => l.name}
          subtitleOf={(l) => l.proficiency}
          fields={[
            { key: "name", label: "Language", kind: "text", required: true },
            {
              key: "proficiency",
              label: "Proficiency",
              kind: "select",
              options: ["basic", "conversational", "professional", "fluent", "native"],
            },
          ]}
        />
      )}
      {tab === "contacts" && (
        <GenericEntityPanel<Contact>
          endpoint="/api/v1/history/contacts"
          title="Contacts"
          entityType="contact"
          labelOf={(c) => c.name}
          subtitleOf={(c) =>
            [c.role, c.organization_name].filter(Boolean).join(" · ") || null
          }
          fields={[
            { key: "name", label: "Name", kind: "text", required: true, fullWidth: true },
            { key: "role", label: "Role", kind: "text" },
            {
              key: "relationship_type",
              label: "Relationship",
              kind: "select",
              options: ["recruiter", "referral", "hiring_manager", "peer", "mentor", "other"],
            },
            { key: "email", label: "Email", kind: "text" },
            { key: "phone", label: "Phone", kind: "text" },
            { key: "linkedin_url", label: "LinkedIn URL", kind: "url", fullWidth: true },
            { key: "last_contacted_date", label: "Last contacted", kind: "date" },
            { key: "notes", label: "Notes", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
      {tab === "custom" && (
        <GenericEntityPanel<CustomEvent>
          endpoint="/api/v1/history/custom-events"
          title="Custom Events"
          entityType="custom"
          labelOf={(e) => e.title}
          subtitleOf={(e) =>
            [e.type_label, e.start_date, e.end_date].filter(Boolean).join(" · ") || null
          }
          emptyHint="Catch-all for anything dated that doesn't fit another category."
          fields={[
            { key: "title", label: "Title", kind: "text", required: true, fullWidth: true },
            { key: "type_label", label: "Type", kind: "text", required: true },
            { key: "start_date", label: "Start date", kind: "date" },
            { key: "end_date", label: "End date", kind: "date" },
            { key: "description", label: "Description", kind: "textarea", fullWidth: true },
          ]}
        />
      )}
    </PageShell>
  );
}

