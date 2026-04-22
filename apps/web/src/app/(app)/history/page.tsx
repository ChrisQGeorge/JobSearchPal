"use client";

import { useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";
import { EducationPanel } from "./_panels/EducationPanel";
import { SkillsPanel } from "./_panels/SkillsPanel";
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
  const [ingestOpen, setIngestOpen] = useState(false);
  return (
    <PageShell
      title="History Editor"
      subtitle="Your canonical career record. Every AI skill draws from what is recorded here — and nothing else."
      actions={
        <button
          className="jsp-btn-primary"
          onClick={() => setIngestOpen(true)}
          title="Upload an old resume and let the Companion propose entries"
        >
          Import from resume
        </button>
      }
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
      {tab === "skills" && <SkillsPanel />}
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
              options: [
                // Work
                "manager", "co_worker", "direct_report", "skip_level",
                "recruiter", "hiring_manager", "peer",
                // School
                "professor", "advisor", "classmate", "teaching_assistant",
                // Projects
                "project_partner", "collaborator", "open_source_maintainer",
                // Generic
                "referral", "mentor", "mentee", "friend", "family", "other",
              ],
            },
            {
              key: "can_use_as_reference",
              label: "Can use as reference",
              kind: "select",
              options: ["yes", "no", "unknown"],
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
      {ingestOpen ? (
        <ResumeIngestModal onClose={() => setIngestOpen(false)} />
      ) : null}
    </PageShell>
  );
}

// ---------- Resume ingest modal ---------------------------------------------

type IngestResult = {
  proposals: {
    work_experiences: Array<Record<string, unknown>>;
    educations: Array<Record<string, unknown>>;
    skills: string[];
    projects: Array<Record<string, unknown>>;
  };
  warning?: string | null;
  created?: {
    work_experiences: number;
    educations: number;
    skills: number;
    projects: number;
  } | null;
};

function ResumeIngestModal({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [docId, setDocId] = useState<number | null>(null);
  const [status, setStatus] = useState<
    "pick" | "uploading" | "analyzing" | "review" | "committing" | "done"
  >("pick");
  const [result, setResult] = useState<IngestResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function upload(f: File) {
    setFile(f);
    setErr(null);
    setStatus("uploading");
    try {
      const fd = new FormData();
      fd.append("file", f);
      fd.append("doc_type", "resume");
      const res = await fetch("/api/v1/documents/upload", {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      if (!res.ok) throw new Error(`Upload HTTP ${res.status}`);
      const doc = (await res.json()) as { id: number };
      setDocId(doc.id);
      setStatus("analyzing");
      const analyzed = await api.post<IngestResult>(
        "/api/v1/history/resume-ingest",
        { document_id: doc.id, dry_run: true },
      );
      setResult(analyzed);
      setStatus("review");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ingest failed.");
      setStatus("pick");
    }
  }

  async function commit() {
    if (!docId) return;
    setStatus("committing");
    setErr(null);
    try {
      const r = await api.post<IngestResult>("/api/v1/history/resume-ingest", {
        document_id: docId,
        dry_run: false,
      });
      setResult(r);
      setStatus("done");
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Commit failed.");
      setStatus("review");
    }
  }

  const counts = result
    ? {
        w: result.proposals.work_experiences.length,
        e: result.proposals.educations.length,
        s: result.proposals.skills.length,
        p: result.proposals.projects.length,
      }
    : null;

  return (
    <>
      <button
        type="button"
        aria-label="close"
        className="fixed inset-0 z-30 bg-black/60"
        onClick={onClose}
      />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 jsp-card shadow-2xl p-5 w-[min(720px,92vw)] max-h-[85vh] overflow-auto space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-sm uppercase tracking-wider text-corp-muted">
              Import from resume
            </h3>
            <p className="text-[11px] text-corp-muted mt-1">
              Upload an old resume — PDF, DOCX, or text — and the Companion
              will propose work experiences, education, skills, and projects.
              Nothing is written until you confirm.
            </p>
          </div>
          <button className="jsp-btn-ghost text-xs" onClick={onClose}>
            Close
          </button>
        </div>

        {status === "pick" ? (
          <label className="jsp-btn-primary inline-flex cursor-pointer">
            Choose resume file…
            <input
              type="file"
              className="hidden"
              accept=".pdf,.docx,.txt,.md,.html,.htm,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/*"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
              }}
            />
          </label>
        ) : null}

        {status === "uploading" ? (
          <p className="text-sm text-corp-muted">Uploading {file?.name}…</p>
        ) : null}

        {status === "analyzing" ? (
          <p className="text-sm text-corp-muted animate-pulse">
            Companion is reading {file?.name}… this can take up to a minute.
          </p>
        ) : null}

        {err ? <div className="text-xs text-corp-danger">{err}</div> : null}

        {status === "review" && result && counts ? (
          <>
            {result.warning ? (
              <div className="text-xs text-corp-accent2 bg-corp-accent2/10 border border-corp-accent2/40 p-2 rounded">
                ⚠ {result.warning}
              </div>
            ) : null}
            <div className="text-sm">
              Found <strong>{counts.w}</strong> work, <strong>{counts.e}</strong>{" "}
              education, <strong>{counts.s}</strong> skills, <strong>{counts.p}</strong>{" "}
              projects.
            </div>
            <IngestPreview proposals={result.proposals} />
            <div className="flex justify-end gap-2">
              <button className="jsp-btn-ghost" onClick={onClose} type="button">
                Cancel
              </button>
              <button className="jsp-btn-primary" onClick={commit} type="button">
                Create all
              </button>
            </div>
          </>
        ) : null}

        {status === "committing" ? (
          <p className="text-sm text-corp-muted animate-pulse">Writing entities…</p>
        ) : null}

        {status === "done" && result?.created ? (
          <div className="space-y-2">
            <p className="text-sm text-corp-accent">
              Imported: {result.created.work_experiences} work,{" "}
              {result.created.educations} education, {result.created.skills} skills,{" "}
              {result.created.projects} projects.
            </p>
            <div className="flex justify-end">
              <button className="jsp-btn-primary" onClick={onClose} type="button">
                Done — reload to see them
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}

function IngestPreview({
  proposals,
}: {
  proposals: IngestResult["proposals"];
}) {
  return (
    <div className="space-y-2 max-h-[45vh] overflow-auto">
      {proposals.work_experiences.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Work
          </div>
          <ul className="text-xs space-y-1">
            {proposals.work_experiences.map((w, i) => (
              <li key={i} className="jsp-card p-2">
                <div>
                  <strong>{String(w.title ?? "")}</strong>
                  {w.organization_name ? ` · ${String(w.organization_name)}` : ""}
                </div>
                <div className="text-corp-muted">
                  {String(w.start_date ?? "?")} — {String(w.end_date ?? "present")}
                  {w.location ? ` · ${String(w.location)}` : ""}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {proposals.educations.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Education
          </div>
          <ul className="text-xs space-y-1">
            {proposals.educations.map((e, i) => (
              <li key={i} className="jsp-card p-2">
                <div>
                  <strong>{String(e.degree ?? "")}</strong>
                  {e.field_of_study ? ` · ${String(e.field_of_study)}` : ""}
                </div>
                <div className="text-corp-muted">
                  {String(e.organization_name ?? "")} ·{" "}
                  {String(e.start_date ?? "?")} — {String(e.end_date ?? "?")}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {proposals.skills.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Skills
          </div>
          <div className="flex flex-wrap gap-1">
            {proposals.skills.map((s, i) => (
              <span
                key={i}
                className="text-[11px] px-1.5 py-0.5 rounded bg-corp-surface2 border border-corp-border"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {proposals.projects.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Projects
          </div>
          <ul className="text-xs space-y-1">
            {proposals.projects.map((p, i) => (
              <li key={i} className="jsp-card p-2">
                <div>
                  <strong>{String(p.name ?? "")}</strong>
                  {p.role ? ` · ${String(p.role)}` : ""}
                </div>
                {p.summary ? (
                  <div className="text-corp-muted">{String(p.summary)}</div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

