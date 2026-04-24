"use client";

import Link from "next/link";
import { useEffect, useRef, useState, use as usePromise } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { OrganizationCombobox } from "@/components/OrganizationCombobox";
import { PageShell } from "@/components/PageShell";
import { SkillsAnalysis } from "@/components/SkillsAnalysis";
import { StatusBadge } from "@/components/StatusBadge";
import { api, apiUrl, ApiError } from "@/lib/api";
import {
  ARTIFACT_KINDS,
  EDUCATION_REQUIRED,
  EMPLOYMENT_TYPES,
  EXPERIENCE_LEVELS,
  JOB_STATUSES,
  type ApplicationEvent,
  type EducationRequired,
  type EmploymentType,
  type ExperienceLevel,
  type InterviewArtifact,
  type InterviewArtifactKind,
  type InterviewRound,
  type InterviewRoundOutcome,
  type JobStatus,
  type Priority,
  DOC_TYPES,
  type Contact,
  type DocType,
  type GeneratedDocument,
  type JdAnalysis,
  type RemotePolicy,
  type TrackedJob,
} from "@/lib/types";

type Tab =
  | "overview"
  | "rounds"
  | "artifacts"
  | "contacts"
  | "documents"
  | "activity";

type EntityLinkOut = {
  id: number;
  from_entity_type: string;
  from_entity_id: number;
  to_entity_type: string;
  to_entity_id: number;
  relation?: string | null;
  note?: string | null;
  to_label?: string | null;
};

export default function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  // Next 15 makes params a Promise in client components. React.use() unwraps it.
  const { id } = usePromise(params);
  const jobId = Number(id);
  const router = useRouter();
  const [job, setJob] = useState<TrackedJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("overview");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      setJob(await api.get<TrackedJob>(`/api/v1/jobs/${jobId}`));
      setErr(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setErr("Job not found.");
      } else {
        setErr("Failed to load job.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!Number.isFinite(jobId)) {
      setErr("Invalid job id.");
      setLoading(false);
      return;
    }
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  async function patch(updates: Partial<TrackedJob>) {
    if (!job) return;
    setSaving(true);
    try {
      setJob(await api.put<TrackedJob>(`/api/v1/jobs/${jobId}`, updates));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm("Delete this job? Interview rounds and events go with it.")) return;
    await api.delete(`/api/v1/jobs/${jobId}`);
    router.replace("/jobs");
  }

  if (loading) {
    return (
      <PageShell title="Job Detail">
        <p className="text-corp-muted">Loading...</p>
      </PageShell>
    );
  }
  if (err || !job) {
    return (
      <PageShell title="Job Detail">
        <div className="jsp-card p-6 text-sm text-corp-danger">{err}</div>
        <Link href="/jobs" className="jsp-btn-ghost inline-block mt-4">
          ← Back to Job Tracker
        </Link>
      </PageShell>
    );
  }

  return (
    <PageShell
      title={job.title}
      subtitle={
        job.organization_name
          ? `${job.organization_name}${job.location ? " · " + job.location : ""}`
          : job.location ?? undefined
      }
      actions={
        <div className="flex gap-2 items-center flex-wrap">
          <ReviewAction
            jobId={job.id}
            status={job.status}
            onStatusChanged={(s) => patch({ status: s })}
          />
          <WriteDocButton jobId={job.id} docType="resume" label="Write resume" />
          <WriteDocButton
            jobId={job.id}
            docType="cover_letter"
            label="Write cover letter"
          />
          <ProgressStatusButton
            status={job.status}
            disabled={saving}
            onAdvance={(s) => patch({ status: s })}
          />
          <StatusSelect
            status={job.status}
            disabled={saving}
            onChange={(s) => patch({ status: s })}
          />
          <button
            className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
            onClick={remove}
          >
            Delete
          </button>
        </div>
      }
    >
      <Link href="/jobs" className="text-sm text-corp-muted hover:text-corp-accent">
        ← All jobs
      </Link>

      <div className="flex gap-2 mt-4 mb-4 border-b border-corp-border">
        {(
          [
            ["overview", "Overview"],
            ["rounds", "Interview Rounds"],
            ["artifacts", "Artifacts"],
            ["contacts", "Contacts"],
            ["documents", "Documents"],
            ["activity", "Activity"],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-3 py-2 text-sm transition-colors ${
              tab === k
                ? "text-corp-accent border-b-2 border-corp-accent"
                : "text-corp-muted hover:text-corp-text"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewTab job={job} onSaved={setJob} />}
      {tab === "rounds" && <RoundsTab jobId={jobId} />}
      {tab === "artifacts" && <ArtifactsTab jobId={jobId} />}
      {tab === "contacts" && <ContactsTab jobId={jobId} />}
      {tab === "documents" && <DocumentsTab jobId={jobId} />}
      {tab === "activity" && <ActivityTab jobId={jobId} />}
    </PageShell>
  );
}

function StatusSelect({
  status,
  disabled,
  onChange,
}: {
  status: JobStatus;
  disabled?: boolean;
  onChange: (s: JobStatus) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <StatusBadge status={status} />
      <select
        className="jsp-input w-40"
        value={status}
        onChange={(e) => onChange(e.target.value as JobStatus)}
        disabled={disabled}
      >
        {JOB_STATUSES.map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
    </div>
  );
}

/**
 * The review-queue "Reviewed · Next →" button. Always visible so a user
 * browsing any job can clear it out of review + jump to the next. The
 * button's behavior depends on the current status:
 *
 *   status == "to_review" — marks the row as `reviewed` AND advances to
 *       the next to_review job. If the user has already picked a more
 *       specific status via the dropdown (applied / interested / …), the
 *       current status counts as "already reviewed" and we just advance.
 *   status != "to_review" — the status flip is a no-op; clicking still
 *       advances to the next to_review job. Lets the user skim through
 *       already-reviewed jobs without changing their status by accident.
 *
 * Counter shows remaining jobs in the review queue (excluding the current
 * one if it's still to_review — the Reviewed click will decrement it).
 */
// Header shortcut: fire a tailor for resume or cover_letter with the
// identical call the Documents tab's Write button uses, then drop the
// user straight into the Studio editor on the placeholder doc. The
// editor polls the doc until tailoring completes so the user sees the
// "Generating…" banner flip to the real content without any further
// clicks.
function WriteDocButton({
  jobId,
  docType,
  label,
}: {
  jobId: number;
  docType: "resume" | "cover_letter";
  label: string;
}) {
  const router = useRouter();
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setErr(null);
    try {
      const doc = await api.post<GeneratedDocument>(
        `/api/v1/documents/tailor/${jobId}`,
        { doc_type: docType },
      );
      router.push(`/studio/${doc.id}`);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `HTTP ${e.status}`
          : "Failed",
      );
      setTimeout(() => setErr(null), 5000);
    } finally {
      setRunning(false);
    }
  }

  return (
    <button
      type="button"
      className="jsp-btn-ghost text-xs"
      onClick={run}
      disabled={running}
      title={`Run the tailor with doc_type=${docType}, then open the draft in Studio`}
    >
      {running ? "Queuing…" : err ? `Failed: ${err}` : label}
    </button>
  );
}

// Ordered stage progression per the user's preferred pipeline.
// Each entry maps current status → next status. Terminal states
// (not in the map) hide the button.
const _NEXT_STAGE: Partial<Record<JobStatus, JobStatus>> = {
  to_review: "reviewed",
  reviewed: "interested",
  interested: "applied",
  applied: "responded",
  responded: "interviewing",
  interviewing: "assessment",
  assessment: "offer",
  offer: "won",
};

const _STAGE_LABEL: Partial<Record<JobStatus, string>> = {
  reviewed: "reviewed",
  interested: "interested",
  applied: "applied",
  responded: "replied",
  interviewing: "interviewing",
  assessment: "assessment",
  offer: "offer",
  won: "won",
};

function ProgressStatusButton({
  status,
  disabled,
  onAdvance,
}: {
  status: JobStatus;
  disabled?: boolean;
  onAdvance: (next: JobStatus) => void;
}) {
  const next = _NEXT_STAGE[status];
  if (!next) {
    // Terminal status (won / lost / withdrawn / ghosted / archived /
    // not_interested) — no next stage, hide the button entirely.
    return null;
  }
  const nextLabel = _STAGE_LABEL[next] ?? next;
  return (
    <button
      type="button"
      className="jsp-btn-primary text-xs"
      onClick={() => onAdvance(next)}
      disabled={disabled}
      title={`Advance status from "${status}" → "${next}"`}
    >
      → {nextLabel}
    </button>
  );
}


function ReviewAction({
  jobId,
  status,
  onStatusChanged,
}: {
  jobId: number;
  status: JobStatus;
  onStatusChanged: (s: JobStatus) => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inReviewFlow = searchParams.get("from") === "review";
  const [ids, setIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);

  async function refreshQueue() {
    try {
      const out = await api.get<{ ids: number[] }>(
        "/api/v1/jobs/review-queue",
      );
      setIds(out.ids ?? []);
    } catch {
      /* best-effort — worst case counter shows zero */
    }
  }

  useEffect(() => {
    refreshQueue();
  }, [jobId]);

  // How many still need review after this one? If current status is
  // already not-to-review, the count = full queue. If current IS
  // to_review, subtract 1 because clicking the button will clear it.
  const remaining =
    status === "to_review"
      ? Math.max(0, ids.filter((i) => i !== jobId).length)
      : ids.length;

  async function act() {
    setBusy(true);
    try {
      if (status === "to_review") {
        await api.put<TrackedJob>(`/api/v1/jobs/${jobId}`, {
          status: "reviewed",
        });
        onStatusChanged("reviewed");
      }
      // Compute next target — prefer the next to_review after the current
      // one in the queue, wrap to the first if we're already at the end,
      // or fall back to the Review Queue list page if the queue is empty.
      const queue = ids.filter((i) => i !== jobId);
      if (queue.length === 0) {
        router.push("/jobs/review");
        return;
      }
      const idx = ids.indexOf(jobId);
      const next = idx >= 0 && idx + 1 < ids.length ? ids[idx + 1] : queue[0];
      router.push(`/jobs/${next}?from=review`);
    } catch {
      /* non-fatal; stay on the page */
    } finally {
      setBusy(false);
    }
  }

  const label =
    status === "to_review"
      ? `Reviewed · Next →`
      : inReviewFlow
        ? `Skip · Next →`
        : `Next to review →`;

  // Counter is only meaningful when there's at least one waiting job.
  const counter =
    remaining > 0 ? (
      <span className="text-[10px] text-corp-muted ml-1">
        ({remaining} left)
      </span>
    ) : null;

  return (
    <button
      type="button"
      className="jsp-btn-primary flex items-center gap-1"
      onClick={act}
      disabled={busy}
      title={
        status === "to_review"
          ? "Mark this job as reviewed and move to the next one in the queue"
          : "Move to the next to-review job"
      }
    >
      {busy ? "..." : label}
      {counter}
    </button>
  );
}

// ---------- Overview tab -----------------------------------------------------

function OverviewTab({
  job,
  onSaved,
}: {
  job: TrackedJob;
  onSaved: (j: TrackedJob) => void;
}) {
  const [form, setForm] = useState<TrackedJob>(job);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setForm(job);
  }, [job]);

  const dirty =
    JSON.stringify(
      Object.fromEntries(Object.entries(form).filter(([k]) => !["created_at", "updated_at", "organization_name"].includes(k))),
    ) !==
    JSON.stringify(
      Object.fromEntries(Object.entries(job).filter(([k]) => !["created_at", "updated_at", "organization_name"].includes(k))),
    );

  async function save() {
    setSaving(true);
    try {
      const payload: Partial<TrackedJob> = {
        title: form.title,
        organization_id: form.organization_id,
        job_description: form.job_description,
        source_url: form.source_url,
        location: form.location,
        remote_policy: form.remote_policy,
        priority: form.priority,
        notes: form.notes,
        salary_min: form.salary_min,
        salary_max: form.salary_max,
        salary_currency: form.salary_currency,
        date_posted: form.date_posted,
        date_discovered: form.date_discovered,
        date_applied: form.date_applied,
        date_closed: form.date_closed,
        experience_years_min: form.experience_years_min,
        experience_years_max: form.experience_years_max,
        experience_level: form.experience_level,
        employment_type: form.employment_type,
        education_required: form.education_required,
        visa_sponsorship_offered: form.visa_sponsorship_offered,
        relocation_offered: form.relocation_offered,
        required_skills: form.required_skills,
        nice_to_have_skills: form.nice_to_have_skills,
      };
      onSaved(await api.put<TrackedJob>(`/api/v1/jobs/${job.id}`, payload));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      {job.organization_id ? (
        <CompanyResearchPanel
          organizationId={job.organization_id}
          organizationName={job.organization_name ?? null}
        />
      ) : null}
      <JdAnalysisPanel
        job={job}
        onAnalyzed={onSaved}
      />
      <AutofillPanel jobId={job.id} />
      {(job.required_skills && job.required_skills.length > 0) ||
      (job.nice_to_have_skills && job.nice_to_have_skills.length > 0) ? (
        <SkillsAnalysis
          required={job.required_skills ?? null}
          niceToHave={job.nice_to_have_skills ?? null}
        />
      ) : null}
    <div className="jsp-card p-5 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="jsp-label">Title</label>
          <input
            className="jsp-input"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </div>
        <div>
          <label className="jsp-label">Organization</label>
          <OrganizationCombobox
            value={form.organization_id ?? null}
            onChange={(id) => setForm({ ...form, organization_id: id })}
            defaultTypeOnCreate="company"
          />
        </div>
        <div>
          <label className="jsp-label">Priority</label>
          <select
            className="jsp-input"
            value={form.priority ?? ""}
            onChange={(e) =>
              setForm({ ...form, priority: (e.target.value || null) as Priority | null })
            }
          >
            <option value="">—</option>
            <option>low</option>
            <option>medium</option>
            <option>high</option>
          </select>
        </div>
        <div>
          <label className="jsp-label">Location</label>
          <input
            className="jsp-input"
            value={form.location ?? ""}
            onChange={(e) => setForm({ ...form, location: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">Remote policy</label>
          <select
            className="jsp-input"
            value={form.remote_policy ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                remote_policy: (e.target.value || null) as RemotePolicy | null,
              })
            }
          >
            <option value="">—</option>
            <option>onsite</option>
            <option>hybrid</option>
            <option>remote</option>
          </select>
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Source URL</label>
          <input
            className="jsp-input"
            value={form.source_url ?? ""}
            onChange={(e) => setForm({ ...form, source_url: e.target.value || null })}
          />
        </div>
        <div>
          <label className="jsp-label">Date discovered</label>
          <input
            type="date"
            className="jsp-input"
            value={form.date_discovered ?? ""}
            onChange={(e) =>
              setForm({ ...form, date_discovered: e.target.value || null })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Date applied</label>
          <input
            type="date"
            className="jsp-input"
            value={form.date_applied ?? ""}
            onChange={(e) =>
              setForm({ ...form, date_applied: e.target.value || null })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Date closed</label>
          <input
            type="date"
            className="jsp-input"
            value={form.date_closed ?? ""}
            onChange={(e) =>
              setForm({ ...form, date_closed: e.target.value || null })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Salary min</label>
          <input
            type="number"
            className="jsp-input"
            value={form.salary_min ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                salary_min: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Salary max</label>
          <input
            type="number"
            className="jsp-input"
            value={form.salary_max ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                salary_max: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Currency</label>
          <input
            className="jsp-input"
            placeholder="USD"
            value={form.salary_currency ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                salary_currency: e.target.value.toUpperCase().slice(0, 8) || null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Date posted</label>
          <input
            type="date"
            className="jsp-input"
            value={form.date_posted ?? ""}
            onChange={(e) =>
              setForm({ ...form, date_posted: e.target.value || null })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Employment type</label>
          <select
            className="jsp-input"
            value={form.employment_type ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                employment_type: (e.target.value || null) as EmploymentType | null,
              })
            }
          >
            <option value="">—</option>
            {EMPLOYMENT_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Experience level</label>
          <select
            className="jsp-input"
            value={form.experience_level ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                experience_level: (e.target.value || null) as ExperienceLevel | null,
              })
            }
          >
            <option value="">—</option>
            {EXPERIENCE_LEVELS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Years experience min</label>
          <input
            type="number"
            className="jsp-input"
            value={form.experience_years_min ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                experience_years_min: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Years experience max</label>
          <input
            type="number"
            className="jsp-input"
            value={form.experience_years_max ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                experience_years_max: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Education required</label>
          <select
            className="jsp-input"
            value={form.education_required ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                education_required: (e.target.value || null) as EducationRequired | null,
              })
            }
          >
            <option value="">—</option>
            {EDUCATION_REQUIRED.map((e) => (
              <option key={e}>{e}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Visa sponsorship</label>
          <select
            className="jsp-input"
            value={
              form.visa_sponsorship_offered == null
                ? ""
                : form.visa_sponsorship_offered
                  ? "yes"
                  : "no"
            }
            onChange={(e) =>
              setForm({
                ...form,
                visa_sponsorship_offered:
                  e.target.value === "" ? null : e.target.value === "yes",
              })
            }
          >
            <option value="">— (not stated)</option>
            <option value="yes">Offered</option>
            <option value="no">Not offered</option>
          </select>
        </div>
        <div>
          <label className="jsp-label">Relocation</label>
          <select
            className="jsp-input"
            value={
              form.relocation_offered == null
                ? ""
                : form.relocation_offered
                  ? "yes"
                  : "no"
            }
            onChange={(e) =>
              setForm({
                ...form,
                relocation_offered:
                  e.target.value === "" ? null : e.target.value === "yes",
              })
            }
          >
            <option value="">— (not stated)</option>
            <option value="yes">Offered</option>
            <option value="no">Not offered</option>
          </select>
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Job description</label>
          <textarea
            className="jsp-input min-h-[160px]"
            value={form.job_description ?? ""}
            onChange={(e) =>
              setForm({ ...form, job_description: e.target.value || null })
            }
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Notes</label>
          <textarea
            className="jsp-input min-h-[100px]"
            value={form.notes ?? ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value || null })}
          />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          className="jsp-btn-ghost"
          onClick={() => setForm(job)}
          disabled={!dirty}
        >
          Reset
        </button>
        <button
          type="button"
          className="jsp-btn-primary"
          onClick={save}
          disabled={!dirty || saving}
        >
          {saving ? "..." : "Save changes"}
        </button>
      </div>
    </div>
    </div>
  );
}

// ---------- Rounds tab -------------------------------------------------------

const OUTCOMES: InterviewRoundOutcome[] = ["pending", "passed", "failed", "mixed", "unknown"];

function RoundsTab({ jobId }: { jobId: number }) {
  const [rounds, setRounds] = useState<InterviewRound[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setRounds(await api.get<InterviewRound[]>(`/api/v1/jobs/${jobId}/rounds`));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const nextNum = rounds.reduce((m, r) => Math.max(m, r.round_number), 0) + 1;

  async function remove(id: number) {
    if (!confirm("Delete this round?")) return;
    await api.delete(`/api/v1/jobs/${jobId}/rounds/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
          + New Round
        </button>
      </div>

      {creating ? (
        <div className="jsp-card p-4">
          <RoundForm
            jobId={jobId}
            initial={{ round_number: nextNum }}
            onCancel={() => setCreating(false)}
            onSaved={() => {
              setCreating(false);
              refresh();
            }}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted">Loading rounds...</p>
      ) : rounds.length === 0 && !creating ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          No rounds recorded. Add one when you&apos;ve scheduled or completed an
          interview.
        </div>
      ) : (
        <ul className="space-y-2">
          {rounds.map((r) => (
            <RoundRow key={r.id} jobId={jobId} round={r} onChanged={refresh} onDelete={() => remove(r.id)} />
          ))}
        </ul>
      )}
    </div>
  );
}

function RoundRow({
  jobId,
  round,
  onChanged,
  onDelete,
}: {
  jobId: number;
  round: InterviewRound;
  onChanged: () => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [prepping, setPrepping] = useState(false);
  const [retroOpen, setRetroOpen] = useState(false);
  const [skillErr, setSkillErr] = useState<string | null>(null);

  async function runPrep() {
    setPrepping(true);
    setSkillErr(null);
    try {
      await api.post(`/api/v1/jobs/${jobId}/rounds/${round.id}/prep`, {});
      onChanged();
    } catch (e) {
      setSkillErr(
        e instanceof ApiError ? `Prep failed (HTTP ${e.status}).` : "Prep failed.",
      );
    } finally {
      setPrepping(false);
    }
  }

  if (editing) {
    return (
      <li className="jsp-card p-4">
        <RoundForm
          jobId={jobId}
          initial={round}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            onChanged();
          }}
        />
      </li>
    );
  }

  if (retroOpen) {
    return (
      <li className="jsp-card p-4">
        <RetrospectiveForm
          jobId={jobId}
          roundId={round.id}
          onCancel={() => setRetroOpen(false)}
          onSaved={() => {
            setRetroOpen(false);
            onChanged();
          }}
        />
      </li>
    );
  }

  return (
    <li className="jsp-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-corp-accent font-semibold">
              Round {round.round_number}
            </span>
            {round.round_type ? (
              <span className="text-[10px] uppercase tracking-wider text-corp-muted">
                {round.round_type}
              </span>
            ) : null}
            <OutcomePill outcome={round.outcome} />
          </div>
          <div className="text-sm text-corp-muted mt-1">
            {round.scheduled_at
              ? new Date(round.scheduled_at).toLocaleString()
              : "unscheduled"}
            {round.format ? ` · ${round.format}` : ""}
            {round.duration_minutes ? ` · ${round.duration_minutes} min` : ""}
          </div>
          {round.location_or_link ? (
            <div className="text-sm text-corp-muted truncate max-w-xl">
              {round.location_or_link.startsWith("http") ? (
                <a
                  href={round.location_or_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-corp-accent hover:underline"
                >
                  {round.location_or_link}
                </a>
              ) : (
                round.location_or_link
              )}
            </div>
          ) : null}
          {round.self_rating ? (
            <div className="text-sm text-corp-muted">
              Self-rating: {"★".repeat(round.self_rating)}
              {"☆".repeat(5 - round.self_rating)}
            </div>
          ) : null}
          {round.notes_md ? (
            <p className="text-sm mt-2 whitespace-pre-wrap">{round.notes_md}</p>
          ) : null}
        </div>
        <div className="flex gap-2 shrink-0 flex-wrap justify-end">
          <button
            className="jsp-btn-ghost text-xs"
            onClick={runPrep}
            disabled={prepping}
            title="Ask the Companion to draft a prep doc (saves to prep_notes_md)"
          >
            {prepping ? "Prepping..." : "Prep"}
          </button>
          <button
            className="jsp-btn-ghost text-xs"
            onClick={() => setRetroOpen(true)}
            title="Write a retrospective after the round"
          >
            Retro
          </button>
          <button className="jsp-btn-ghost" onClick={() => setEditing(true)}>
            Edit
          </button>
          <button
            className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
            onClick={onDelete}
          >
            Delete
          </button>
        </div>
      </div>
      {skillErr ? (
        <div className="text-xs text-corp-danger mt-2">{skillErr}</div>
      ) : null}
    </li>
  );
}

function RetrospectiveForm({
  jobId,
  roundId,
  onCancel,
  onSaved,
}: {
  jobId: number;
  roundId: number;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [recap, setRecap] = useState("");
  const [selfRating, setSelfRating] = useState<number | "">("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{
    retrospective_md: string;
    went_well: string[];
    went_poorly: string[];
    skill_gaps_observed: string[];
    topics_to_brush_up: string[];
    followup_action?: string | null;
    rerun_confidence?: number | null;
    warning?: string | null;
  } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!recap.trim()) {
      setErr("Describe the round first.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const r = await api.post<typeof result & object>(
        `/api/v1/jobs/${jobId}/rounds/${roundId}/retrospective`,
        {
          user_recap: recap,
          self_rating: selfRating === "" ? null : Number(selfRating),
        },
      );
      setResult(r);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Retrospective failed (HTTP ${e.status}).` : "Retrospective failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (result) {
    return (
      <div className="space-y-3">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">
          Retrospective saved
        </h3>
        {result.warning ? (
          <div className="text-xs text-corp-accent2 bg-corp-accent2/10 border border-corp-accent2/40 p-2 rounded">
            ⚠ {result.warning}
          </div>
        ) : null}
        {result.rerun_confidence !== null && result.rerun_confidence !== undefined ? (
          <div className="text-xs text-corp-muted">
            Re-run confidence: {result.rerun_confidence}/100
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-3 text-sm">
          {result.went_well.length ? (
            <BulletGroup label="Went well" items={result.went_well} tone="good" />
          ) : null}
          {result.went_poorly.length ? (
            <BulletGroup label="Went poorly" items={result.went_poorly} tone="warn" />
          ) : null}
          {result.skill_gaps_observed.length ? (
            <BulletGroup
              label="Skill gaps surfaced"
              items={result.skill_gaps_observed}
            />
          ) : null}
          {result.topics_to_brush_up.length ? (
            <BulletGroup label="Brush up" items={result.topics_to_brush_up} />
          ) : null}
        </div>
        {result.followup_action ? (
          <div className="text-sm">
            <span className="text-[10px] uppercase tracking-wider text-corp-accent">
              Follow-up:
            </span>{" "}
            {result.followup_action}
          </div>
        ) : null}
        <pre className="text-sm whitespace-pre-wrap font-mono bg-corp-surface2 border border-corp-border p-3 rounded max-h-80 overflow-auto">
          {result.retrospective_md}
        </pre>
        <div className="flex justify-end">
          <button className="jsp-btn-primary" onClick={onSaved} type="button">
            Close
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <h3 className="text-sm uppercase tracking-wider text-corp-muted">
        Interview retrospective
      </h3>
      <p className="text-[11px] text-corp-muted">
        Paste or dictate a raw recap of the round — what they asked, how you
        answered, what felt off. The Companion structures it into wins, gaps,
        and brush-up topics.
      </p>
      <div>
        <label className="jsp-label">Raw recap</label>
        <textarea
          className="jsp-input min-h-[140px]"
          value={recap}
          onChange={(e) => setRecap(e.target.value)}
          placeholder="They asked about X. I explained Y but stumbled on Z…"
        />
      </div>
      <div>
        <label className="jsp-label">Self-rating (1–5, optional)</label>
        <input
          type="number"
          min={1}
          max={5}
          className="jsp-input w-28"
          value={selfRating}
          onChange={(e) =>
            setSelfRating(e.target.value === "" ? "" : Number(e.target.value))
          }
        />
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "Writing..." : "Write retrospective"}
        </button>
      </div>
    </form>
  );
}

function BulletGroup({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone?: "good" | "warn";
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-300"
      : tone === "warn"
        ? "text-corp-accent2"
        : "text-corp-muted";
  return (
    <div>
      <div className={`text-[10px] uppercase tracking-wider mb-1 ${toneClass}`}>
        {label}
      </div>
      <ul className="list-disc list-inside space-y-0.5">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

function OutcomePill({ outcome }: { outcome: InterviewRoundOutcome }) {
  const cls =
    outcome === "passed"
      ? "bg-emerald-500/25 text-emerald-300 border-emerald-500/40"
      : outcome === "failed"
        ? "bg-corp-danger/20 text-corp-danger border-corp-danger/40"
        : outcome === "mixed"
          ? "bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40"
          : outcome === "unknown"
            ? "bg-corp-surface2 text-corp-muted border-corp-border"
            : "bg-sky-500/20 text-sky-300 border-sky-500/40"; // pending
  return (
    <span className={`inline-block px-2 py-0.5 rounded border text-[10px] uppercase tracking-wider ${cls}`}>
      {outcome}
    </span>
  );
}

function RoundForm({
  jobId,
  initial,
  onCancel,
  onSaved,
}: {
  jobId: number;
  initial: Partial<InterviewRound>;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<Partial<InterviewRound>>({
    round_number: 1,
    outcome: "pending",
    ...initial,
  });
  const [saving, setSaving] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        round_number: form.round_number ?? 1,
        round_type: form.round_type ?? null,
        scheduled_at: form.scheduled_at ?? null,
        duration_minutes: form.duration_minutes ?? null,
        format: form.format ?? null,
        location_or_link: form.location_or_link ?? null,
        outcome: form.outcome ?? "pending",
        self_rating: form.self_rating ?? null,
        notes_md: form.notes_md ?? null,
        prep_notes_md: form.prep_notes_md ?? null,
      };
      if (initial.id) {
        await api.put(`/api/v1/jobs/${jobId}/rounds/${initial.id}`, payload);
      } else {
        await api.post(`/api/v1/jobs/${jobId}/rounds`, payload);
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  // Scheduled_at requires a local datetime string for the <input type="datetime-local">.
  const scheduledValue = form.scheduled_at
    ? new Date(form.scheduled_at).toISOString().slice(0, 16)
    : "";

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Round #</label>
          <input
            type="number"
            min={1}
            className="jsp-input"
            value={form.round_number ?? 1}
            onChange={(e) => setForm({ ...form, round_number: Number(e.target.value) })}
          />
        </div>
        <div>
          <label className="jsp-label">Type</label>
          <select
            className="jsp-input"
            value={form.round_type ?? ""}
            onChange={(e) => setForm({ ...form, round_type: e.target.value || null })}
          >
            <option value="">—</option>
            {[
              "recruiter_screen",
              "hiring_manager",
              "technical",
              "system_design",
              "behavioral",
              "panel",
              "take_home",
              "onsite",
              "final",
              "other",
            ].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Scheduled at</label>
          <input
            type="datetime-local"
            className="jsp-input"
            value={scheduledValue}
            onChange={(e) =>
              setForm({
                ...form,
                scheduled_at: e.target.value
                  ? new Date(e.target.value).toISOString()
                  : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Duration (min)</label>
          <input
            type="number"
            className="jsp-input"
            value={form.duration_minutes ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                duration_minutes: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Format</label>
          <select
            className="jsp-input"
            value={form.format ?? ""}
            onChange={(e) => setForm({ ...form, format: e.target.value || null })}
          >
            <option value="">—</option>
            <option>phone</option>
            <option>video</option>
            <option>in_person</option>
          </select>
        </div>
        <div>
          <label className="jsp-label">Outcome</label>
          <select
            className="jsp-input"
            value={form.outcome ?? "pending"}
            onChange={(e) =>
              setForm({ ...form, outcome: e.target.value as InterviewRoundOutcome })
            }
          >
            {OUTCOMES.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Location / link</label>
          <input
            className="jsp-input"
            value={form.location_or_link ?? ""}
            onChange={(e) =>
              setForm({ ...form, location_or_link: e.target.value || null })
            }
          />
        </div>
        <div>
          <label className="jsp-label">Self rating (1–5)</label>
          <input
            type="number"
            min={1}
            max={5}
            className="jsp-input"
            value={form.self_rating ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                self_rating: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div />
        <div className="col-span-2">
          <label className="jsp-label">Prep notes</label>
          <textarea
            className="jsp-input min-h-[60px]"
            value={form.prep_notes_md ?? ""}
            onChange={(e) =>
              setForm({ ...form, prep_notes_md: e.target.value || null })
            }
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Post-round notes</label>
          <textarea
            className="jsp-input min-h-[80px]"
            value={form.notes_md ?? ""}
            onChange={(e) =>
              setForm({ ...form, notes_md: e.target.value || null })
            }
          />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "..." : "Save"}
        </button>
      </div>
    </form>
  );
}

// ---------- Activity tab -----------------------------------------------------

function ActivityTab({ jobId }: { jobId: number }) {
  const [events, setEvents] = useState<ApplicationEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setEvents(await api.get<ApplicationEvent[]>(`/api/v1/jobs/${jobId}/events`));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  async function addNote(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    setSaving(true);
    try {
      await api.post(`/api/v1/jobs/${jobId}/events`, {
        event_type: "note",
        details_md: draft.trim(),
      });
      setDraft("");
      await refresh();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      <form onSubmit={addNote} className="jsp-card p-4 flex gap-2 items-start">
        <textarea
          className="jsp-input flex-1 min-h-[60px]"
          placeholder="Log a note or event — spoke with recruiter, received rejection, etc."
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className="jsp-btn-primary" disabled={saving || !draft.trim()}>
          {saving ? "..." : "Log"}
        </button>
      </form>
      {loading ? (
        <p className="text-corp-muted">Loading...</p>
      ) : events.length === 0 ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">No activity yet.</div>
      ) : (
        <ol className="relative border-l border-corp-border pl-4 space-y-2">
          {events.map((ev) => (
            <li key={ev.id} className="jsp-card p-3">
              <div className="flex justify-between gap-3 items-baseline">
                <span className="text-[10px] uppercase tracking-wider text-corp-accent">
                  {ev.event_type}
                </span>
                <span className="text-[10px] text-corp-muted">
                  {new Date(ev.event_date).toLocaleString()}
                </span>
              </div>
              {ev.details_md ? (
                <p className="text-sm mt-1 whitespace-pre-wrap">{ev.details_md}</p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------- Artifacts tab ----------------------------------------------------

function ArtifactsTab({ jobId }: { jobId: number }) {
  const [artifacts, setArtifacts] = useState<InterviewArtifact[]>([]);
  const [rounds, setRounds] = useState<InterviewRound[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [a, r] = await Promise.all([
        api.get<InterviewArtifact[]>(`/api/v1/jobs/${jobId}/artifacts`),
        api.get<InterviewRound[]>(`/api/v1/jobs/${jobId}/rounds`),
      ]);
      setArtifacts(a);
      setRounds(r);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  async function remove(id: number) {
    if (!confirm("Delete this artifact?")) return;
    await api.delete(`/api/v1/jobs/${jobId}/artifacts/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <p className="text-xs text-corp-muted">
          Take-home prompts, whiteboard snapshots, feedback notes, recruiter
          emails, offer letters — anything from the pipeline worth keeping.
        </p>
        <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
          + New Artifact
        </button>
      </div>

      {creating ? (
        <div className="jsp-card p-4">
          <ArtifactForm
            jobId={jobId}
            rounds={rounds}
            initial={{}}
            onCancel={() => setCreating(false)}
            onSaved={() => {
              setCreating(false);
              refresh();
            }}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted">Loading artifacts...</p>
      ) : artifacts.length === 0 && !creating ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          No artifacts yet. Paste in a take-home prompt or feedback note so
          the Companion can reference it later.
        </div>
      ) : (
        <ul className="space-y-2">
          {artifacts.map((a) =>
            editingId === a.id ? (
              <li key={a.id} className="jsp-card p-4">
                <ArtifactForm
                  jobId={jobId}
                  rounds={rounds}
                  initial={a}
                  onCancel={() => setEditingId(null)}
                  onSaved={() => {
                    setEditingId(null);
                    refresh();
                  }}
                />
              </li>
            ) : (
              <ArtifactRow
                key={a.id}
                artifact={a}
                roundNumber={
                  rounds.find((r) => r.id === a.interview_round_id)?.round_number ?? null
                }
                onEdit={() => setEditingId(a.id)}
                onDelete={() => remove(a.id)}
              />
            ),
          )}
        </ul>
      )}
    </div>
  );
}

function ArtifactRow({
  artifact,
  roundNumber,
  onEdit,
  onDelete,
}: {
  artifact: InterviewArtifact;
  roundNumber: number | null;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const body = artifact.content_md ?? "";
  const hasLongBody = body.length > 240;
  return (
    <li className="jsp-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-corp-accent font-semibold">{artifact.title}</span>
            <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border">
              {artifact.kind.replace(/_/g, " ")}
            </span>
            {roundNumber !== null ? (
              <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-sky-500/20 text-sky-300 border border-sky-500/40">
                Round {roundNumber}
              </span>
            ) : null}
            {artifact.source ? (
              <span className="text-[10px] text-corp-muted">· {artifact.source}</span>
            ) : null}
          </div>
          {artifact.file_url ? (
            <div className="mt-1">
              <a
                href={
                  artifact.file_url.startsWith("/api/v1/")
                    ? apiUrl(artifact.file_url)
                    : artifact.file_url
                }
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-corp-accent hover:underline break-all"
              >
                {artifact.source === "uploaded"
                  ? `Open ${artifact.title}`
                  : artifact.file_url}
              </a>
            </div>
          ) : null}
          {artifact.tags && artifact.tags.length > 0 ? (
            <div className="mt-1 flex gap-1 flex-wrap">
              {artifact.tags.map((t) => (
                <span
                  key={t}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-corp-surface2 text-corp-muted border border-corp-border"
                >
                  {t}
                </span>
              ))}
            </div>
          ) : null}
          {body ? (
            <div className="mt-2">
              <p className="text-sm whitespace-pre-wrap">
                {expanded || !hasLongBody ? body : body.slice(0, 240) + "…"}
              </p>
              {hasLongBody ? (
                <button
                  type="button"
                  className="text-xs text-corp-muted hover:text-corp-accent mt-1"
                  onClick={() => setExpanded((v) => !v)}
                >
                  {expanded ? "Show less" : "Show more"}
                </button>
              ) : null}
            </div>
          ) : null}
          <div className="text-[10px] text-corp-muted mt-2">
            {new Date(artifact.created_at).toLocaleString()}
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <button className="jsp-btn-ghost" onClick={onEdit}>
            Edit
          </button>
          <button
            className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
            onClick={onDelete}
          >
            Delete
          </button>
        </div>
      </div>
    </li>
  );
}

function ArtifactForm({
  jobId,
  rounds,
  initial,
  onCancel,
  onSaved,
}: {
  jobId: number;
  rounds: InterviewRound[];
  initial: Partial<InterviewArtifact>;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<Partial<InterviewArtifact>>({
    kind: "notes",
    ...initial,
  });
  const [tagsText, setTagsText] = useState<string>((initial.tags ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title?.trim()) {
      setErr("Title is required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const tags = tagsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const payload = {
        kind: form.kind as InterviewArtifactKind,
        title: form.title.trim(),
        interview_round_id: form.interview_round_id ?? null,
        file_url: form.file_url?.trim() || null,
        mime_type: form.mime_type?.trim() || null,
        content_md: form.content_md ?? null,
        source: form.source?.trim() || null,
        tags: tags.length ? tags : null,
      };
      if (initial.id) {
        await api.put(`/api/v1/jobs/${jobId}/artifacts/${initial.id}`, payload);
      } else {
        await api.post(`/api/v1/jobs/${jobId}/artifacts`, payload);
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Kind</label>
          <select
            className="jsp-input"
            value={form.kind ?? "notes"}
            onChange={(e) =>
              setForm({ ...form, kind: e.target.value as InterviewArtifactKind })
            }
          >
            {ARTIFACT_KINDS.map((k) => (
              <option key={k} value={k}>
                {k.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Linked round (optional)</label>
          <select
            className="jsp-input"
            value={form.interview_round_id ?? ""}
            onChange={(e) =>
              setForm({
                ...form,
                interview_round_id: e.target.value ? Number(e.target.value) : null,
              })
            }
          >
            <option value="">— job-level (not round-specific)</option>
            {rounds.map((r) => (
              <option key={r.id} value={r.id}>
                Round {r.round_number}
                {r.round_type ? ` · ${r.round_type}` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Title</label>
          <input
            className="jsp-input"
            value={form.title ?? ""}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Take-home: inventory service design"
          />
        </div>
        <div>
          <label className="jsp-label">Source (optional)</label>
          <input
            className="jsp-input"
            value={form.source ?? ""}
            onChange={(e) => setForm({ ...form, source: e.target.value })}
            placeholder="uploaded / generated / pasted / other"
          />
        </div>
        <div>
          <label className="jsp-label">Tags (comma-separated)</label>
          <input
            className="jsp-input"
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
            placeholder="system-design, favorites"
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">File URL (optional)</label>
          <input
            className="jsp-input"
            value={form.file_url ?? ""}
            onChange={(e) => setForm({ ...form, file_url: e.target.value })}
            placeholder="https://..."
          />
        </div>
        {!initial.id ? (
          <div className="col-span-2">
            <ArtifactFileUpload
              jobId={jobId}
              form={form}
              tagsText={tagsText}
              onSaved={onSaved}
              setErr={setErr}
            />
          </div>
        ) : null}
        <div className="col-span-2">
          <label className="jsp-label">Content (markdown)</label>
          <textarea
            className="jsp-input min-h-[160px]"
            value={form.content_md ?? ""}
            onChange={(e) => setForm({ ...form, content_md: e.target.value })}
            placeholder="Paste the prompt, feedback notes, offer terms, etc."
          />
        </div>
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "Saving..." : initial.id ? "Save" : "Create"}
        </button>
      </div>
    </form>
  );
}

function ArtifactFileUpload({
  jobId,
  form,
  tagsText,
  onSaved,
  setErr,
}: {
  jobId: number;
  form: Partial<InterviewArtifact>;
  tagsText: string;
  onSaved: () => void;
  setErr: (s: string | null) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function handle(file: File) {
    setUploading(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("kind", form.kind || "other");
      if (form.title?.trim()) fd.append("title", form.title.trim());
      if (form.interview_round_id != null)
        fd.append("interview_round_id", String(form.interview_round_id));
      if (tagsText.trim()) fd.append("tags", tagsText.trim());
      const res = await fetch(
        apiUrl(`/api/v1/jobs/${jobId}/artifacts/upload`),
        { method: "POST", credentials: "include", body: fd },
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status}: ${txt.slice(0, 240)}`);
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="flex items-center gap-2">
      <label
        className={`jsp-btn-ghost text-xs cursor-pointer inline-flex ${
          uploading ? "opacity-50 pointer-events-none" : ""
        }`}
      >
        {uploading ? "Uploading..." : "Upload file directly"}
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handle(f);
          }}
        />
      </label>
      <span className="text-[11px] text-corp-muted">
        or paste a URL / content below and click Create instead.
      </span>
    </div>
  );
}

// ---------- Contacts tab -----------------------------------------------------

function ContactsTab({ jobId }: { jobId: number }) {
  const [links, setLinks] = useState<EntityLinkOut[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);
  const [pickId, setPickId] = useState<number | "">("");
  const [relation, setRelation] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const [ls, cs] = await Promise.all([
        api.get<EntityLinkOut[]>(
          `/api/v1/history/links?from_entity_type=tracked_job&from_entity_id=${jobId}`,
        ),
        api.get<Contact[]>("/api/v1/history/contacts"),
      ]);
      setLinks(ls.filter((l) => l.to_entity_type === "contact"));
      setContacts(cs);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const alreadyLinked = new Set(links.map((l) => l.to_entity_id));
  const available = contacts.filter((c) => !alreadyLinked.has(c.id));

  async function linkContact(e: React.FormEvent) {
    e.preventDefault();
    if (pickId === "") return;
    setSaving(true);
    setErr(null);
    try {
      await api.post("/api/v1/history/links", {
        from_entity_type: "tracked_job",
        from_entity_id: jobId,
        to_entity_type: "contact",
        to_entity_id: Number(pickId),
        relation: relation.trim() || null,
        note: note.trim() || null,
      });
      setPickId("");
      setRelation("");
      setNote("");
      setPicking(false);
      await refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? `Link failed (HTTP ${e.status}).` : "Link failed.");
    } finally {
      setSaving(false);
    }
  }

  async function unlink(linkId: number) {
    if (!confirm("Remove this contact link? (The contact record itself stays.)")) return;
    await api.delete(`/api/v1/history/links/${linkId}`);
    await refresh();
  }

  const contactById = new Map(contacts.map((c) => [c.id, c]));

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-start">
        <p className="text-xs text-corp-muted">
          Recruiter, hiring manager, referrer, interviewer — link people from
          your contacts list so the Companion can stitch them into prep and
          follow-up.{" "}
          <Link href="/history" className="text-corp-accent hover:underline">
            Manage contacts →
          </Link>
        </p>
        <button className="jsp-btn-primary" onClick={() => setPicking(true)}>
          + Link Contact
        </button>
      </div>

      {picking ? (
        <form onSubmit={linkContact} className="jsp-card p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="jsp-label">Contact</label>
              <select
                className="jsp-input"
                value={pickId}
                onChange={(e) => setPickId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">— pick an existing contact —</option>
                {available.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.role ? ` · ${c.role}` : ""}
                    {c.organization_name ? ` · ${c.organization_name}` : ""}
                  </option>
                ))}
              </select>
              {available.length === 0 ? (
                <p className="text-[11px] text-corp-muted mt-1">
                  No unlinked contacts. Add one under{" "}
                  <Link href="/history" className="text-corp-accent hover:underline">
                    History
                  </Link>
                  .
                </p>
              ) : null}
            </div>
            <div>
              <label className="jsp-label">Relation (optional)</label>
              <input
                className="jsp-input"
                value={relation}
                onChange={(e) => setRelation(e.target.value)}
                placeholder="recruiter / hiring manager / referrer / interviewer"
              />
            </div>
            <div className="col-span-2">
              <label className="jsp-label">Note (optional)</label>
              <input
                className="jsp-input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="First spoke at the Boston meetup"
              />
            </div>
          </div>
          {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="jsp-btn-ghost"
              onClick={() => {
                setPicking(false);
                setErr(null);
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="jsp-btn-primary"
              disabled={saving || pickId === ""}
            >
              {saving ? "..." : "Link"}
            </button>
          </div>
        </form>
      ) : null}

      {loading ? (
        <p className="text-corp-muted">Loading contacts...</p>
      ) : links.length === 0 && !picking ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          No contacts linked yet.
        </div>
      ) : (
        <ul className="space-y-2">
          {links.map((l) => {
            const c = contactById.get(l.to_entity_id);
            return (
              <li key={l.id} className="jsp-card p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-corp-accent font-semibold">
                        {l.to_label ?? c?.name ?? `Contact #${l.to_entity_id}`}
                      </span>
                      {l.relation ? (
                        <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border">
                          {l.relation}
                        </span>
                      ) : null}
                      {c?.role ? (
                        <span className="text-[11px] text-corp-muted">· {c.role}</span>
                      ) : null}
                      {c?.organization_name ? (
                        <span className="text-[11px] text-corp-muted">
                          · {c.organization_name}
                        </span>
                      ) : null}
                    </div>
                    <div className="text-xs text-corp-muted mt-1 flex flex-wrap gap-x-3 gap-y-1">
                      {c?.email ? (
                        <a
                          href={`mailto:${c.email}`}
                          className="hover:text-corp-accent"
                        >
                          {c.email}
                        </a>
                      ) : null}
                      {c?.phone ? <span>{c.phone}</span> : null}
                      {c?.linkedin_url ? (
                        <a
                          href={c.linkedin_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-corp-accent"
                        >
                          LinkedIn
                        </a>
                      ) : null}
                    </div>
                    {l.note ? (
                      <p className="text-sm mt-2 whitespace-pre-wrap">{l.note}</p>
                    ) : null}
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button
                      className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
                      onClick={() => unlink(l.id)}
                    >
                      Unlink
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ---------- JD Analysis panel (shown on Overview) ---------------------------

function JdAnalysisPanel({
  job,
  onAnalyzed,
}: {
  job: TrackedJob;
  onAnalyzed: (j: TrackedJob) => void;
}) {
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const analysis = (job.jd_analysis ?? null) as JdAnalysis | null;
  const hasDescription = !!(job.job_description && job.job_description.trim());

  async function run() {
    setRunning(true);
    setErr(null);
    try {
      const updated = await api.post<TrackedJob>(
        `/api/v1/jobs/${job.id}/analyze-jd`,
        {},
      );
      onAnalyzed(updated);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Analysis failed (HTTP ${e.status}).` : "Analysis failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  if (!analysis) {
    return (
      <div className="jsp-card p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm uppercase tracking-wider text-corp-muted">
              JD Analysis
            </h3>
            <p className="text-sm text-corp-muted mt-1">
              {hasDescription
                ? "Run the Companion against the stored JD to surface fit score, gaps, red flags, and prep focus."
                : "Paste a job description below first — the analyzer reads it verbatim."}
            </p>
          </div>
          <button
            className="jsp-btn-primary"
            onClick={run}
            disabled={running || !hasDescription}
          >
            {running ? "Analyzing..." : "Analyze JD"}
          </button>
        </div>
        {err ? <div className="text-xs text-corp-danger mt-2">{err}</div> : null}
      </div>
    );
  }

  const score = analysis.fit_score ?? null;
  const scoreColor =
    score === null
      ? "text-corp-muted"
      : score >= 75
        ? "text-emerald-300"
        : score >= 50
          ? "text-corp-accent2"
          : "text-corp-danger";

  return (
    <div className="jsp-card p-5 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            JD Analysis
          </h3>
          {analysis.fit_summary ? (
            <p className="text-sm mt-1">{analysis.fit_summary}</p>
          ) : null}
        </div>
        <div className="flex flex-col items-end gap-2">
          {score !== null ? (
            <div className={`text-3xl font-semibold ${scoreColor}`}>
              {score}
              <span className="text-sm text-corp-muted">/100</span>
            </div>
          ) : null}
          <button className="jsp-btn-ghost text-xs" onClick={run} disabled={running}>
            {running ? "..." : "Re-analyze"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <BulletList label="Strengths" items={analysis.strengths} tone="good" />
        <BulletList label="Gaps" items={analysis.gaps} tone="warn" />
        <BulletList
          label="Green flags (posting)"
          items={analysis.green_flags}
          tone="good"
        />
        <BulletList
          label="Red flags (posting)"
          items={analysis.red_flags}
          tone="danger"
        />
        <BulletList
          label="Interview focus"
          items={analysis.interview_focus_areas}
        />
        <BulletList
          label="Questions to ask"
          items={analysis.suggested_questions}
        />
        <BulletList label="Resume emphasis" items={analysis.resume_emphasis} />
        {analysis.cover_letter_hook ? (
          <div>
            <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
              Cover letter hook
            </div>
            <p className="text-sm whitespace-pre-wrap">
              {analysis.cover_letter_hook}
            </p>
          </div>
        ) : null}
      </div>

      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
    </div>
  );
}

function BulletList({
  label,
  items,
  tone,
}: {
  label: string;
  items?: string[] | null;
  tone?: "good" | "warn" | "danger";
}) {
  if (!items || items.length === 0) return null;
  const toneClass =
    tone === "good"
      ? "text-emerald-300"
      : tone === "warn"
        ? "text-corp-accent2"
        : tone === "danger"
          ? "text-corp-danger"
          : "text-corp-muted";
  return (
    <div>
      <div className={`text-[10px] uppercase tracking-wider mb-1 ${toneClass}`}>
        {label}
      </div>
      <ul className="text-sm list-disc list-inside space-y-0.5">
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

// ---------- Documents tab ---------------------------------------------------

function DocumentsTab({ jobId }: { jobId: number }) {
  const [docs, setDocs] = useState<GeneratedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [writeDocType, setWriteDocType] = useState<DocType>("resume");
  const [writeTitle, setWriteTitle] = useState("");
  const [extraNotes, setExtraNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadDocType, setUploadDocType] = useState<DocType>("other");
  const [uploadTitle, setUploadTitle] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function upload(file: File) {
    setUploading(true);
    setErr(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("tracked_job_id", String(jobId));
      form.append("doc_type", uploadDocType);
      if (uploadTitle.trim()) form.append("title", uploadTitle.trim());
      const res = await fetch(apiUrl("/api/v1/documents/upload"), {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text.slice(0, 300)}`);
      }
      setUploadTitle("");
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? `Upload failed: ${e.message}` : "Upload failed.");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function refresh() {
    setLoading(true);
    try {
      const data = await api.get<GeneratedDocument[]>(
        `/api/v1/documents?tracked_job_id=${jobId}`,
      );
      setDocs(data);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  async function write() {
    setRunning(true);
    setErr(null);
    try {
      await api.post<GeneratedDocument>(`/api/v1/documents/tailor/${jobId}`, {
        doc_type: writeDocType,
        extra_notes: extraNotes.trim() || null,
        title: writeTitle.trim() || null,
      });
      setExtraNotes("");
      setWriteTitle("");
      await refresh();
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Tailoring failed (HTTP ${e.status}).`
          : "Tailoring failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  async function removeDoc(id: number) {
    if (!confirm("Delete this document?")) return;
    await api.delete(`/api/v1/documents/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="jsp-card p-4 space-y-3">
        <div>
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Upload existing document
          </h3>
          <p className="text-[11px] text-corp-muted mt-1">
            Stash historic PDFs, DOCX files, signed offer letters, references —
            anything worth keeping alongside the AI-tailored versions. Max 25 MB.
          </p>
        </div>
        <div className="grid grid-cols-[160px_1fr_auto] gap-2 items-end">
          <div>
            <label className="jsp-label">Type</label>
            <select
              className="jsp-input"
              value={uploadDocType}
              onChange={(e) => setUploadDocType(e.target.value as DocType)}
              disabled={uploading}
            >
              {DOC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="jsp-label">Title (optional — defaults to filename)</label>
            <input
              className="jsp-input"
              value={uploadTitle}
              onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="2024 master resume"
              disabled={uploading}
            />
          </div>
          <div>
            <label className="jsp-label invisible">Upload</label>
            <label
              className={`jsp-btn-primary cursor-pointer inline-flex ${
                uploading ? "opacity-50 pointer-events-none" : ""
              }`}
            >
              {uploading ? "Uploading..." : "Choose file..."}
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload(f);
                }}
              />
            </label>
          </div>
        </div>
      </div>

      <div className="jsp-card p-4 space-y-3">
        <div>
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Write with the Companion
          </h3>
          <p className="text-[11px] text-corp-muted mt-1">
            Picks a prompt based on the type. Resumes and cover letters use
            structured prompts; outreach / thank-you / follow-up emails use an
            email prompt; everything else follows your guidance below.
          </p>
        </div>
        <div className="grid grid-cols-[160px_1fr] gap-2 items-end">
          <div>
            <label className="jsp-label">Type</label>
            <select
              className="jsp-input"
              value={writeDocType}
              onChange={(e) => setWriteDocType(e.target.value as DocType)}
              disabled={running}
            >
              {DOC_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="jsp-label">Title (optional — Companion picks one otherwise)</label>
            <input
              className="jsp-input"
              value={writeTitle}
              onChange={(e) => setWriteTitle(e.target.value)}
              placeholder="Cover letter v3 — emphasize infra"
              disabled={running}
            />
          </div>
        </div>
        <div>
          <label className="jsp-label">Extra guidance (optional)</label>
          <textarea
            className="jsp-input min-h-[60px]"
            placeholder="Emphasize distributed systems work. Keep the cover letter under 250 words. Drop the academic section."
            value={extraNotes}
            onChange={(e) => setExtraNotes(e.target.value)}
            disabled={running}
          />
        </div>
        <div className="flex gap-2 justify-end">
          <button
            className="jsp-btn-primary"
            onClick={write}
            disabled={running}
          >
            {running ? "Writing..." : "Write"}
          </button>
        </div>
        {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
        <p className="text-[11px] text-corp-muted">
          The Companion reads your stored work history + the JD. Can take a
          minute or two. Every run is saved as a new version.
        </p>
      </div>

      {loading ? (
        <p className="text-corp-muted">Loading documents...</p>
      ) : docs.length === 0 ? (
        <div className="jsp-card p-6 text-sm text-corp-muted">
          No documents yet. Upload an existing one or tailor a new one.
        </div>
      ) : (
        <ul className="jsp-card divide-y divide-corp-border">
          {docs.map((d) => (
            <DocumentListRow
              key={d.id}
              doc={d}
              onDelete={() => removeDoc(d.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function DocumentListRow({
  doc,
  onDelete,
}: {
  doc: GeneratedDocument;
  onDelete: () => void;
}) {
  const structured = (doc.content_structured ?? null) as
    | {
        original_filename?: string | null;
        stored_path?: string | null;
        mime_type?: string | null;
        size_bytes?: number | null;
      }
    | null;

  const isUpload = !!structured?.stored_path;
  const fileUrl = isUpload ? apiUrl(`/api/v1/documents/${doc.id}/file`) : null;
  const downloadUrl = isUpload
    ? apiUrl(`/api/v1/documents/${doc.id}/file?download=1`)
    : null;
  const sizeLabel =
    structured?.size_bytes != null
      ? structured.size_bytes > 1_000_000
        ? `${(structured.size_bytes / 1_000_000).toFixed(1)} MB`
        : `${Math.max(1, Math.round(structured.size_bytes / 1024))} KB`
      : null;

  const editorHref = `/studio/${doc.id}`;

  const subline = [
    isUpload ? "uploaded" : "written",
    structured?.original_filename,
    sizeLabel,
    new Date(doc.created_at).toLocaleString(),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className="flex items-center gap-3 py-2 px-4">
      <span className="inline-block px-2 py-0.5 rounded text-[10px] uppercase tracking-wider bg-corp-surface2 text-corp-muted border border-corp-border shrink-0">
        {doc.doc_type.replace(/_/g, " ")}
      </span>
      <span className="text-[10px] text-corp-muted shrink-0 w-8">
        v{doc.version}
      </span>
      <div className="flex-1 min-w-0">
        <a
          href={editorHref}
          className="text-sm truncate hover:text-corp-accent block"
        >
          {doc.title}
        </a>
        <div className="text-[11px] text-corp-muted truncate">{subline}</div>
      </div>
      <div className="flex gap-1.5 shrink-0">
        <a className="jsp-btn-ghost text-xs" href={editorHref}>
          Editor
        </a>
        {fileUrl ? (
          <a
            className="jsp-btn-ghost text-xs"
            href={fileUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open
          </a>
        ) : null}
        {downloadUrl ? (
          <a className="jsp-btn-ghost text-xs" href={downloadUrl}>
            Download
          </a>
        ) : null}
        <button
          className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
          onClick={onDelete}
        >
          Delete
        </button>
      </div>
    </li>
  );
}

// ---------- Company research panel ------------------------------------------

type OrgFull = {
  id: number;
  name: string;
  website?: string | null;
  industry?: string | null;
  size?: string | null;
  headquarters_location?: string | null;
  founded_year?: number | null;
  description?: string | null;
  research_notes?: string | null;
  source_links?: string[] | null;
  tech_stack_hints?: string[] | null;
  reputation_signals?: {
    engineering_culture?: string | null;
    work_life_balance?: string | null;
    layoff_history?: string | null;
    recent_news?: string | null;
    red_flags?: string[] | null;
    green_flags?: string[] | null;
  } | null;
};

function CompanyResearchPanel({
  organizationId,
  organizationName,
}: {
  organizationId: number;
  organizationName: string | null;
}) {
  const [org, setOrg] = useState<OrgFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [hint, setHint] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setOrg(await api.get<OrgFull>(`/api/v1/organizations/${organizationId}`));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organizationId]);

  async function research() {
    setRunning(true);
    setErr(null);
    try {
      const updated = await api.post<OrgFull>(
        `/api/v1/organizations/${organizationId}/research`,
        { hint: hint.trim() || null },
      );
      setOrg(updated);
      setHint("");
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Research failed (HTTP ${e.status}).`
          : "Research failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  if (loading) return null;
  if (!org) return null;

  const rep = org.reputation_signals ?? null;
  const hasAny =
    org.research_notes ||
    (org.tech_stack_hints && org.tech_stack_hints.length) ||
    (org.source_links && org.source_links.length) ||
    rep;

  return (
    <div className="jsp-card p-5 space-y-3">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Company research
          </h3>
          <div className="text-sm mt-1">
            <Link
              href={`/organizations`}
              className="text-corp-accent hover:underline"
            >
              {organizationName ?? org.name}
            </Link>
            {org.industry ? (
              <span className="text-corp-muted"> · {org.industry}</span>
            ) : null}
            {org.size ? (
              <span className="text-corp-muted"> · {org.size}</span>
            ) : null}
            {org.headquarters_location ? (
              <span className="text-corp-muted">
                {" "}
                · {org.headquarters_location}
              </span>
            ) : null}
            {org.website ? (
              <>
                {" · "}
                <a
                  href={org.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-corp-accent hover:underline"
                >
                  website
                </a>
              </>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          className="jsp-btn-primary"
          onClick={research}
          disabled={running}
        >
          {running ? "Researching..." : hasAny ? "Re-research" : "Research company"}
        </button>
      </div>
      <input
        className="jsp-input"
        placeholder="Optional focus: 'recent layoffs', 'engineering culture', 'infra stack'..."
        value={hint}
        onChange={(e) => setHint(e.target.value)}
        disabled={running}
      />
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}

      {org.description ? (
        <p className="text-sm">{org.description}</p>
      ) : null}

      {org.research_notes ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Research notes
          </div>
          <p className="text-sm whitespace-pre-wrap">{org.research_notes}</p>
        </div>
      ) : null}

      {org.tech_stack_hints && org.tech_stack_hints.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Tech stack hints
          </div>
          <div className="flex flex-wrap gap-1">
            {org.tech_stack_hints.map((t) => (
              <span
                key={t}
                className="text-[11px] px-2 py-0.5 rounded bg-corp-surface2 border border-corp-border text-corp-muted"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {rep ? (
        <div className="grid grid-cols-2 gap-3 text-sm">
          {rep.engineering_culture ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                Engineering culture
              </div>
              <div>{rep.engineering_culture}</div>
            </div>
          ) : null}
          {rep.work_life_balance ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                Work/life balance
              </div>
              <div>{rep.work_life_balance}</div>
            </div>
          ) : null}
          {rep.layoff_history ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                Layoff history
              </div>
              <div>{rep.layoff_history}</div>
            </div>
          ) : null}
          {rep.recent_news ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                Recent news
              </div>
              <div>{rep.recent_news}</div>
            </div>
          ) : null}
          {rep.green_flags && rep.green_flags.length > 0 ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-emerald-300">
                Green flags
              </div>
              <ul className="list-disc list-inside space-y-0.5">
                {rep.green_flags.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {rep.red_flags && rep.red_flags.length > 0 ? (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-corp-danger">
                Red flags
              </div>
              <ul className="list-disc list-inside space-y-0.5">
                {rep.red_flags.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {org.source_links && org.source_links.length > 0 ? (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-corp-muted">
            Sources ({org.source_links.length})
          </summary>
          <ul className="mt-1 space-y-0.5">
            {org.source_links.map((l, i) => (
              <li key={i} className="truncate">
                <a
                  href={l}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-corp-accent hover:underline"
                >
                  {l}
                </a>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

type AutofillAnswer = {
  question: string;
  answer: string | null;
  placeholder_keys_used: string[];
  skipped_reason?: string | null;
};

function AutofillPanel({ jobId }: { jobId: number }) {
  const [open, setOpen] = useState(false);
  const [questionsText, setQuestionsText] = useState("");
  const [extra, setExtra] = useState("");
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [out, setOut] = useState<{
    answers: AutofillAnswer[];
    fields_shared: string[];
    warning?: string | null;
    generated_document_id?: number | null;
  } | null>(null);

  async function run() {
    const questions = questionsText
      .split("\n")
      .map((q) => q.trim())
      .filter(Boolean);
    if (!questions.length) {
      setErr("Enter at least one question.");
      return;
    }
    setRunning(true);
    setErr(null);
    setOut(null);
    try {
      const res = await api.post<{
        answers: AutofillAnswer[];
        fields_shared: string[];
        warning?: string | null;
        generated_document_id?: number | null;
      }>("/api/v1/autofill", {
        tracked_job_id: jobId,
        questions,
        extra_notes: extra.trim() || null,
        save_as_document: true,
      });
      setOut(res);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Autofill failed (HTTP ${e.status}).`
          : "Autofill failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
  }

  return (
    <div className="jsp-card p-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">
            Application autofill
          </h3>
          <p className="text-[11px] text-corp-muted mt-1">
            Paste in questions from the application form (one per line). Answers
            come from your Job Preferences + Work Authorization + history.
            Demographic questions resolve via templated substitution — the LLM
            never sees that data as free text.
          </p>
        </div>
        <button
          className="jsp-btn-ghost text-xs"
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {open ? "Hide" : "Open"}
        </button>
      </div>
      {open ? (
        <div className="mt-3 space-y-3">
          <div>
            <label className="jsp-label">Questions (one per line)</label>
            <textarea
              className="jsp-input min-h-[120px]"
              value={questionsText}
              onChange={(e) => setQuestionsText(e.target.value)}
              placeholder={
                "Why are you interested in this role?\nWhat is your target salary?\nDo you need visa sponsorship?"
              }
              disabled={running}
            />
          </div>
          <div>
            <label className="jsp-label">Extra notes (optional)</label>
            <input
              className="jsp-input"
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              placeholder="Keep answers under 150 words."
              disabled={running}
            />
          </div>
          {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
          <div className="flex justify-end">
            <button
              className="jsp-btn-primary"
              onClick={run}
              disabled={running}
              type="button"
            >
              {running ? "Filling..." : "Generate answers"}
            </button>
          </div>

          {out ? (
            <div className="space-y-2">
              {out.warning ? (
                <div className="text-xs text-corp-accent2 bg-corp-accent2/10 border border-corp-accent2/40 p-2 rounded">
                  ⚠ {out.warning}
                </div>
              ) : null}
              {out.generated_document_id ? (
                <div className="flex items-center justify-between gap-2 bg-corp-surface2 border border-corp-border rounded px-3 py-2 text-xs">
                  <span className="text-corp-muted">
                    Saved as a document — open it in Studio to edit, humanize, or export.
                  </span>
                  <Link
                    href={`/studio/${out.generated_document_id}`}
                    className="jsp-btn-primary text-xs shrink-0"
                  >
                    Open in Studio →
                  </Link>
                </div>
              ) : null}
              {out.fields_shared.length ? (
                <div className="text-[11px] text-corp-muted">
                  Templated fields used: {out.fields_shared.join(", ")} (logged
                  to AutofillLog).
                </div>
              ) : null}
              <ul className="space-y-2">
                {out.answers.map((a, i) => (
                  <li
                    key={i}
                    className="jsp-card p-3 bg-corp-surface2"
                  >
                    <div className="text-[11px] uppercase tracking-wider text-corp-muted mb-1">
                      Q{i + 1}: {a.question}
                    </div>
                    {a.answer ? (
                      <>
                        <p className="text-sm whitespace-pre-wrap">{a.answer}</p>
                        <div className="flex justify-between items-center mt-1">
                          <span className="text-[10px] text-corp-muted">
                            {a.placeholder_keys_used.length
                              ? "uses: " + a.placeholder_keys_used.join(", ")
                              : ""}
                          </span>
                          <button
                            type="button"
                            className="jsp-btn-ghost text-xs"
                            onClick={() => copy(a.answer!)}
                          >
                            Copy
                          </button>
                        </div>
                      </>
                    ) : (
                      <p className="text-xs text-corp-accent2 italic">
                        Skipped{a.skipped_reason ? ` — ${a.skipped_reason}` : ""}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
