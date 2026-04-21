"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  downloadExcelTemplate,
  downloadQueueTemplate,
  FetchQueuePanel,
  importExcel,
  importQueueExcel,
} from "@/components/FetchQueuePanel";
import { InlineStatusPicker } from "@/components/InlineStatusPicker";
import { OrganizationCombobox } from "@/components/OrganizationCombobox";
import { PageShell } from "@/components/PageShell";
import { SkillsAnalysis } from "@/components/SkillsAnalysis";
import { StatusBadge, STATUS_STYLES } from "@/components/StatusBadge";
import { api, ApiError } from "@/lib/api";
import {
  EDUCATION_REQUIRED,
  EMPLOYMENT_TYPES,
  EXPERIENCE_LEVELS,
  JOB_STATUSES,
  type EducationRequired,
  type EmploymentType,
  type ExperienceLevel,
  type FetchedJobInfo,
  type JobStatus,
  type Priority,
  type RemotePolicy,
  type TrackedJob,
  type TrackedJobSummary,
} from "@/lib/types";

export default function JobTrackerPage() {
  const [items, setItems] = useState<TrackedJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "">("");
  const [creating, setCreating] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set("status", statusFilter);
      setItems(await api.get<TrackedJobSummary[]>(`/api/v1/jobs?${params.toString()}`));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  // Status counts across the full set (unfiltered). Quick-nav to each bucket.
  const [counts, setCounts] = useState<Partial<Record<JobStatus, number>>>({});
  useEffect(() => {
    api
      .get<TrackedJobSummary[]>("/api/v1/jobs")
      .then((all) => {
        const c: Partial<Record<JobStatus, number>> = {};
        for (const j of all) c[j.status] = (c[j.status] ?? 0) + 1;
        setCounts(c);
      })
      .catch(() => {});
  }, [items.length]);

  const fileInput = useRef<HTMLInputElement>(null);
  const queueFileInput = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [queueImporting, setQueueImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<
    { kind: "ok" | "warn" | "error"; text: string } | null
  >(null);

  async function onImport(file: File | null) {
    if (!file) return;
    setImporting(true);
    setImportMsg(null);
    try {
      const res = await importExcel(file);
      setImportMsg({
        kind: res.skipped_count === 0 ? "ok" : "warn",
        text: `Imported ${res.created_count} job${res.created_count === 1 ? "" : "s"}${
          res.skipped_count ? `, skipped ${res.skipped_count} (see console for row errors)` : ""
        }.`,
      });
      if (res.errors.length > 0) {
        // eslint-disable-next-line no-console
        console.warn("Excel import row errors:", res.errors);
      }
      refresh();
    } catch (err) {
      setImportMsg({
        kind: "error",
        text: err instanceof Error ? err.message : "Import failed.",
      });
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function onQueueImport(file: File | null) {
    if (!file) return;
    setQueueImporting(true);
    setImportMsg(null);
    try {
      const res = await importQueueExcel(file);
      setImportMsg({
        kind: res.skipped_count === 0 ? "ok" : "warn",
        text: `Enqueued ${res.enqueued_count} URL${res.enqueued_count === 1 ? "" : "s"} — the Companion will fetch them in the background${
          res.skipped_count
            ? `, skipped ${res.skipped_count} (see console for row errors)`
            : ""
        }.`,
      });
      if (res.errors.length > 0) {
        // eslint-disable-next-line no-console
        console.warn("Queue import row errors:", res.errors);
      }
      // No refresh() — the queue panel polls on its own.
    } catch (err) {
      setImportMsg({
        kind: "error",
        text: err instanceof Error ? err.message : "Queue import failed.",
      });
    } finally {
      setQueueImporting(false);
      if (queueFileInput.current) queueFileInput.current.value = "";
    }
  }

  return (
    <PageShell
      title="Job Tracker"
      subtitle="Every opportunity, from the first sighting through offer or — let's be honest — ghosting."
      actions={
        <div className="flex gap-2 items-center">
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => downloadExcelTemplate()}
            title="Download a pre-formatted Excel template for bulk import"
          >
            Excel template
          </button>
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => fileInput.current?.click()}
            disabled={importing}
          >
            {importing ? "Importing..." : "Import Excel"}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => onImport(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => downloadQueueTemplate()}
            title="Download the minimal queue-import template: URL + optional dates"
          >
            Queue template
          </button>
          <button
            type="button"
            className="jsp-btn-ghost"
            onClick={() => queueFileInput.current?.click()}
            disabled={queueImporting}
            title="Import a list of URLs into the fetch queue — Companion visits each one"
          >
            {queueImporting ? "Importing..." : "Import queue"}
          </button>
          <input
            ref={queueFileInput}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => onQueueImport(e.target.files?.[0] ?? null)}
          />
          <ScoreAllButton onDone={refresh} />
          <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
            + New Job
          </button>
        </div>
      }
    >
      {importMsg ? (
        <div
          className={
            "jsp-card p-3 mb-3 text-sm " +
            (importMsg.kind === "ok"
              ? "text-corp-ok border-l-4 border-l-corp-ok"
              : importMsg.kind === "warn"
                ? "text-corp-accent2 border-l-4 border-l-corp-accent2"
                : "text-corp-danger border-l-4 border-l-corp-danger")
          }
        >
          {importMsg.text}
        </div>
      ) : null}

      <div className="mb-3">
        <FetchQueuePanel onJobCreated={refresh} />
      </div>

      <StatusFilterPills
        current={statusFilter}
        counts={counts}
        onChange={setStatusFilter}
      />

      {creating ? (
        <div className="jsp-card p-4 mb-4 mt-4">
          <NewJobForm
            onCancel={() => setCreating(false)}
            onSaved={(created) => {
              setCreating(false);
              refresh();
              // bounce into detail for immediate editing
              window.location.href = `/jobs/${created.id}`;
            }}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted mt-4">Loading...</p>
      ) : items.length === 0 ? (
        <div className="jsp-card p-6 text-corp-muted text-sm mt-4">
          {statusFilter
            ? `No jobs with status "${statusFilter}".`
            : "No jobs tracked yet. Add one above — paste a URL, a title, and Claude will fill in the rest as you go."}
        </div>
      ) : (
        <div className="jsp-card mt-4 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-corp-surface2 text-left text-[11px] uppercase tracking-wider text-corp-muted">
                <th className="py-2 px-4">Title</th>
                <th className="py-2 px-4">Organization</th>
                <th className="py-2 px-4">Status</th>
                <th className="py-2 px-4">Fit</th>
                <th className="py-2 px-4">Rounds</th>
                <th className="py-2 px-4">Applied</th>
                <th className="py-2 px-4 text-right">Updated</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr
                  key={j.id}
                  className="border-t border-corp-border hover:bg-corp-surface2 cursor-pointer"
                  onClick={() => (window.location.href = `/jobs/${j.id}`)}
                >
                  <td className="py-2 px-4">
                    <Link href={`/jobs/${j.id}`} className="hover:text-corp-accent">
                      {j.title}
                    </Link>
                    {j.location || j.remote_policy ? (
                      <div className="text-[11px] text-corp-muted mt-0.5">
                        {[j.location, j.remote_policy].filter(Boolean).join(" · ")}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-2 px-4 text-corp-muted">
                    {j.organization_name ?? "—"}
                  </td>
                  <td className="py-2 px-4">
                    <InlineStatusPicker
                      jobId={j.id}
                      status={j.status}
                      onChange={(next) =>
                        setItems((prev) =>
                          prev.map((row) =>
                            row.id === j.id ? { ...row, status: next } : row,
                          ),
                        )
                      }
                    />
                  </td>
                  <td className="py-2 px-4">
                    <FitPill
                      score={j.fit_score ?? null}
                      redFlagCount={j.red_flag_count ?? 0}
                    />
                  </td>
                  <td className="py-2 px-4 text-corp-muted">
                    {j.rounds_count}
                    {j.latest_round_outcome && j.latest_round_outcome !== "pending" ? (
                      <span className="ml-1 text-[10px] uppercase tracking-wider">
                        · {j.latest_round_outcome}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2 px-4 text-corp-muted">
                    {j.date_applied ?? "—"}
                  </td>
                  <td className="py-2 px-4 text-right text-[11px] text-corp-muted">
                    {new Date(j.updated_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}

function StatusFilterPills({
  current,
  counts,
  onChange,
}: {
  current: JobStatus | "";
  counts: Partial<Record<JobStatus, number>>;
  onChange: (s: JobStatus | "") => void;
}) {
  const visible = useMemo(
    () => JOB_STATUSES.filter((s) => (counts[s] ?? 0) > 0 || s === current),
    [counts, current],
  );

  return (
    <div className="flex flex-wrap gap-1.5 items-center">
      <button
        className={`px-2.5 py-1 rounded-md text-xs uppercase tracking-wider border ${
          current === ""
            ? "bg-corp-accent/25 text-corp-accent border-corp-accent/40"
            : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text"
        }`}
        onClick={() => onChange("")}
      >
        All
      </button>
      {visible.map((s) => (
        <button
          key={s}
          onClick={() => onChange(current === s ? "" : s)}
          className={`px-2.5 py-1 rounded-md text-xs uppercase tracking-wider border transition-opacity ${
            STATUS_STYLES[s]
          } ${current && current !== s ? "opacity-40" : ""}`}
        >
          {s}
          {counts[s] ? (
            <span className="ml-1 opacity-70">{counts[s]}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

// ---------- New job form -----------------------------------------------------

function NewJobForm({
  onCancel,
  onSaved,
}: {
  onCancel: () => void;
  onSaved: (job: TrackedJob) => void;
}) {
  const [title, setTitle] = useState("");
  const [organizationId, setOrganizationId] = useState<number | null>(null);
  // Bump this key to force the OrganizationCombobox to re-read its `value`
  // prop after a URL fetch updates the organization_id externally.
  const [orgPickerKey, setOrgPickerKey] = useState(0);
  const [status, setStatus] = useState<JobStatus>("watching");
  const [sourceUrl, setSourceUrl] = useState("");
  const [location, setLocation] = useState("");
  const [remotePolicy, setRemotePolicy] = useState<RemotePolicy | "">("");
  const [priority, setPriority] = useState<Priority | "">("");
  const [jd, setJd] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const [dateApplied, setDateApplied] = useState("");
  const [dateClosed, setDateClosed] = useState("");

  // JD-extracted fields
  const [datePosted, setDatePosted] = useState("");
  const [salaryMin, setSalaryMin] = useState<string>("");
  const [salaryMax, setSalaryMax] = useState<string>("");
  const [salaryCurrency, setSalaryCurrency] = useState("");
  const [expYearsMin, setExpYearsMin] = useState<string>("");
  const [expYearsMax, setExpYearsMax] = useState<string>("");
  const [experienceLevel, setExperienceLevel] = useState<ExperienceLevel | "">("");
  const [employmentType, setEmploymentType] = useState<EmploymentType | "">("");
  const [educationRequired, setEducationRequired] = useState<EducationRequired | "">("");
  const [visaSponsorship, setVisaSponsorship] = useState<"yes" | "no" | "">("");
  const [relocation, setRelocation] = useState<"yes" | "no" | "">("");
  const [requiredSkills, setRequiredSkills] = useState<string[] | null>(null);
  const [niceToHave, setNiceToHave] = useState<string[] | null>(null);

  // Fetch-from-URL state
  const [fetchUrl, setFetchUrl] = useState("");
  const [fetching, setFetching] = useState(false);
  const [fetchMsg, setFetchMsg] = useState<{ kind: "ok" | "warn" | "error"; text: string } | null>(null);

  async function doFetch() {
    const url = fetchUrl.trim();
    if (!url) return;
    setFetching(true);
    setFetchMsg(null);
    try {
      const info = await api.post<FetchedJobInfo>("/api/v1/jobs/fetch-from-url", { url });
      // Populate each field only if the fetch actually provided a value; never
      // clobber what the user already typed.
      if (info.title && !title) setTitle(info.title);
      if (info.location && !location) setLocation(info.location);
      if (info.remote_policy && !remotePolicy) setRemotePolicy(info.remote_policy);
      if (info.job_description && !jd) setJd(info.job_description);
      if (info.source_url && !sourceUrl) setSourceUrl(info.source_url);
      if (info.date_posted && !datePosted) setDatePosted(info.date_posted);
      if (info.salary_min != null && !salaryMin) setSalaryMin(String(info.salary_min));
      if (info.salary_max != null && !salaryMax) setSalaryMax(String(info.salary_max));
      if (info.salary_currency && !salaryCurrency) setSalaryCurrency(info.salary_currency);
      if (info.experience_years_min != null && !expYearsMin)
        setExpYearsMin(String(info.experience_years_min));
      if (info.experience_years_max != null && !expYearsMax)
        setExpYearsMax(String(info.experience_years_max));
      if (info.experience_level && !experienceLevel)
        setExperienceLevel(info.experience_level);
      if (info.employment_type && !employmentType)
        setEmploymentType(info.employment_type);
      if (info.education_required && !educationRequired)
        setEducationRequired(info.education_required);
      if (info.visa_sponsorship_offered != null && !visaSponsorship)
        setVisaSponsorship(info.visa_sponsorship_offered ? "yes" : "no");
      if (info.relocation_offered != null && !relocation)
        setRelocation(info.relocation_offered ? "yes" : "no");
      setRequiredSkills(info.required_skills ?? null);
      setNiceToHave(info.nice_to_have_skills ?? null);

      // Backend resolves or creates the Organization itself and returns its id.
      if (info.organization_id && !organizationId) {
        setOrganizationId(info.organization_id);
        setOrgPickerKey((k) => k + 1);
      }

      if (info.warning) {
        setFetchMsg({ kind: "warn", text: info.warning });
      } else {
        const extras: string[] = [];
        if (info.organization_name) extras.push(info.organization_name);
        if (info.organization_industry) extras.push(info.organization_industry);
        if (info.organization_size) extras.push(info.organization_size);
        const researchLine = info.research_notes ? ` — ${info.research_notes}` : "";
        setFetchMsg({
          kind: "ok",
          text:
            `Prefilled from ${new URL(url).hostname}` +
            (extras.length ? ` (${extras.join(" · ")})` : "") +
            researchLine,
        });
      }
    } catch (err) {
      setFetchMsg({
        kind: "error",
        text:
          err instanceof ApiError
            ? `Fetch failed (HTTP ${err.status}). You can still fill the form manually.`
            : "Fetch failed. You can still fill the form manually.",
      });
    } finally {
      setFetching(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      const payload: Partial<TrackedJob> = {
        title,
        status,
        organization_id: organizationId,
        source_url: sourceUrl || null,
        location: location || null,
        remote_policy: (remotePolicy || null) as RemotePolicy | null,
        priority: (priority || null) as Priority | null,
        job_description: jd || null,
        notes: notes || null,
        date_posted: datePosted || null,
        date_applied: dateApplied || null,
        date_closed: dateClosed || null,
        salary_min: salaryMin ? Number(salaryMin) : null,
        salary_max: salaryMax ? Number(salaryMax) : null,
        salary_currency: salaryCurrency || null,
        experience_years_min: expYearsMin ? Number(expYearsMin) : null,
        experience_years_max: expYearsMax ? Number(expYearsMax) : null,
        experience_level: (experienceLevel || null) as ExperienceLevel | null,
        employment_type: (employmentType || null) as EmploymentType | null,
        education_required:
          (educationRequired || null) as EducationRequired | null,
        visa_sponsorship_offered:
          visaSponsorship === "" ? null : visaSponsorship === "yes",
        relocation_offered: relocation === "" ? null : relocation === "yes",
        required_skills: requiredSkills,
        nice_to_have_skills: niceToHave,
      };
      const created = await api.post<TrackedJob>("/api/v1/jobs", payload);
      onSaved(created);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="jsp-card p-3 border-l-4 border-l-corp-accent/60 space-y-2">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs uppercase tracking-wider text-corp-muted">
            Fetch from URL
          </span>
          <span className="text-[10px] text-corp-muted">
            Paste a job posting link and the Companion will prefill what it can.
          </span>
        </div>
        <div className="flex gap-2">
          <input
            className="jsp-input flex-1 font-mono text-xs"
            placeholder="https://..."
            value={fetchUrl}
            onChange={(e) => setFetchUrl(e.target.value)}
            disabled={fetching}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                doFetch();
              }
            }}
          />
          <button
            type="button"
            className="jsp-btn-primary"
            onClick={doFetch}
            disabled={fetching || !fetchUrl.trim()}
          >
            {fetching ? "Fetching..." : "Fetch"}
          </button>
        </div>
        {fetchMsg ? (
          <div
            className={
              fetchMsg.kind === "ok"
                ? "text-xs text-corp-ok"
                : fetchMsg.kind === "warn"
                  ? "text-xs text-corp-accent2"
                  : "text-xs text-corp-danger"
            }
          >
            {fetchMsg.text}
          </div>
        ) : null}
      </div>

      {(requiredSkills && requiredSkills.length > 0) ||
      (niceToHave && niceToHave.length > 0) ? (
        <SkillsAnalysis required={requiredSkills} niceToHave={niceToHave} />
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="jsp-label">Title</label>
          <input
            className="jsp-input"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Senior Widget Engineer"
          />
        </div>
        <div>
          <label className="jsp-label">Organization</label>
          <OrganizationCombobox
            key={orgPickerKey}
            value={organizationId}
            onChange={setOrganizationId}
            defaultTypeOnCreate="company"
          />
        </div>
        <div>
          <label className="jsp-label">Status</label>
          <select
            className="jsp-input"
            value={status}
            onChange={(e) => setStatus(e.target.value as JobStatus)}
          >
            {JOB_STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Priority</label>
          <select
            className="jsp-input"
            value={priority}
            onChange={(e) => setPriority(e.target.value as Priority | "")}
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
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Remote policy</label>
          <select
            className="jsp-input"
            value={remotePolicy}
            onChange={(e) => setRemotePolicy(e.target.value as RemotePolicy | "")}
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
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://…"
          />
        </div>
        <div>
          <label className="jsp-label">Date posted</label>
          <input
            type="date"
            className="jsp-input"
            value={datePosted}
            onChange={(e) => setDatePosted(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Date applied</label>
          <input
            type="date"
            className="jsp-input"
            value={dateApplied}
            onChange={(e) => setDateApplied(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Date closed</label>
          <input
            type="date"
            className="jsp-input"
            value={dateClosed}
            onChange={(e) => setDateClosed(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Employment type</label>
          <select
            className="jsp-input"
            value={employmentType}
            onChange={(e) =>
              setEmploymentType(e.target.value as EmploymentType | "")
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
            value={experienceLevel}
            onChange={(e) =>
              setExperienceLevel(e.target.value as ExperienceLevel | "")
            }
          >
            <option value="">—</option>
            {EXPERIENCE_LEVELS.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Education required</label>
          <select
            className="jsp-input"
            value={educationRequired}
            onChange={(e) =>
              setEducationRequired(e.target.value as EducationRequired | "")
            }
          >
            <option value="">—</option>
            {EDUCATION_REQUIRED.map((e) => (
              <option key={e}>{e}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="jsp-label">Years experience min</label>
          <input
            type="number"
            className="jsp-input"
            value={expYearsMin}
            onChange={(e) => setExpYearsMin(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Years experience max</label>
          <input
            type="number"
            className="jsp-input"
            value={expYearsMax}
            onChange={(e) => setExpYearsMax(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Salary min</label>
          <input
            type="number"
            className="jsp-input"
            value={salaryMin}
            onChange={(e) => setSalaryMin(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Salary max</label>
          <input
            type="number"
            className="jsp-input"
            value={salaryMax}
            onChange={(e) => setSalaryMax(e.target.value)}
          />
        </div>
        <div>
          <label className="jsp-label">Currency</label>
          <input
            className="jsp-input"
            placeholder="USD"
            value={salaryCurrency}
            onChange={(e) => setSalaryCurrency(e.target.value.toUpperCase().slice(0, 8))}
          />
        </div>
        <div>
          <label className="jsp-label">Visa sponsorship</label>
          <select
            className="jsp-input"
            value={visaSponsorship}
            onChange={(e) => setVisaSponsorship(e.target.value as "" | "yes" | "no")}
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
            value={relocation}
            onChange={(e) => setRelocation(e.target.value as "" | "yes" | "no")}
          >
            <option value="">— (not stated)</option>
            <option value="yes">Offered</option>
            <option value="no">Not offered</option>
          </select>
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Job description</label>
          <textarea
            className="jsp-input min-h-[160px] font-mono text-xs"
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            placeholder="Paste the JD here. Fetch from URL above will populate it verbatim."
          />
        </div>
        <div className="col-span-2">
          <label className="jsp-label">Notes</label>
          <textarea
            className="jsp-input min-h-[60px]"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving || !title.trim()}>
          {saving ? "..." : "Create"}
        </button>
      </div>
    </form>
  );
}

function ScoreAllButton({ onDone }: { onDone: () => void }) {
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setMsg(null);
    try {
      const r = await api.post<{
        analyzed: number;
        skipped_no_description: number;
        skipped_already_scored: number;
        errors: { job_id: number; error: string }[];
      }>("/api/v1/jobs/batch-analyze-jd");
      setMsg(
        `Analyzed ${r.analyzed}${
          r.skipped_already_scored ? ` · ${r.skipped_already_scored} already scored` : ""
        }${r.skipped_no_description ? ` · ${r.skipped_no_description} no JD` : ""}${
          r.errors.length ? ` · ${r.errors.length} errors` : ""
        }`,
      );
      onDone();
    } catch (e) {
      setMsg(
        e instanceof ApiError ? `Batch failed (HTTP ${e.status}).` : "Batch failed.",
      );
    } finally {
      setRunning(false);
      setTimeout(() => setMsg(null), 5000);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className="jsp-btn-ghost"
        onClick={run}
        disabled={running}
        title="Run JD analysis on every unscored job with a description"
      >
        {running ? "Scoring..." : "Score all"}
      </button>
      {msg ? (
        <span className="text-[11px] text-corp-muted">{msg}</span>
      ) : null}
    </div>
  );
}

function FitPill({
  score,
  redFlagCount,
}: {
  score: number | null;
  redFlagCount: number;
}) {
  if (score === null || score === undefined) {
    return (
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-corp-muted">—</span>
        {redFlagCount > 0 ? (
          <span
            className="text-[11px] text-corp-danger"
            title={`${redFlagCount} red flag${redFlagCount === 1 ? "" : "s"} in JD analysis`}
          >
            ⚠{redFlagCount}
          </span>
        ) : null}
      </div>
    );
  }
  const tone =
    score >= 75
      ? "bg-emerald-500/25 text-emerald-300 border-emerald-500/40"
      : score >= 50
        ? "bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40"
        : "bg-corp-danger/20 text-corp-danger border-corp-danger/40";
  return (
    <div className="flex items-center gap-1">
      <span
        className={`inline-block px-2 py-0.5 rounded text-[11px] tabular-nums border ${tone}`}
        title="JD fit score — run the analyzer on the job detail page to update"
      >
        {score}
      </span>
      {redFlagCount > 0 ? (
        <span
          className="text-[11px] text-corp-danger"
          title={`${redFlagCount} red flag${redFlagCount === 1 ? "" : "s"}`}
        >
          ⚠{redFlagCount}
        </span>
      ) : null}
    </div>
  );
}
