"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";

type Tab = "job" | "auth" | "criteria" | "demographics";

const TABS: { key: Tab; label: string }[] = [
  { key: "job", label: "Job Preferences" },
  { key: "auth", label: "Work Authorization" },
  { key: "criteria", label: "Criteria List" },
  { key: "demographics", label: "Demographics" },
];

export default function PreferencesPage() {
  const [tab, setTab] = useState<Tab>("job");
  return (
    <PageShell
      title="Preferences & Identity"
      subtitle="What you want in a job, what you're authorized to do, and voluntary self-identification."
    >
      <div className="flex gap-2 mb-4 border-b border-corp-border">
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
      {tab === "job" && <JobPreferencesPanel />}
      {tab === "auth" && <WorkAuthorizationPanel />}
      {tab === "criteria" && <CriteriaPanel />}
      {tab === "demographics" && <DemographicsPanel />}
    </PageShell>
  );
}

function csvToList(v: string | undefined | null): string[] | null {
  if (!v || !v.trim()) return null;
  const out = v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return out.length ? out : null;
}

function listToCsv(v: string[] | null | undefined): string {
  return (v ?? []).join(", ");
}

function numOrNull(s: string): number | null {
  if (s === "" || s === null || s === undefined) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function SaveBar({
  dirty,
  saving,
  err,
  msg,
  onSave,
}: {
  dirty: boolean;
  saving: boolean;
  err: string | null;
  msg: string | null;
  onSave: () => void;
}) {
  return (
    <div className="flex items-center justify-between pt-2">
      <div className="text-xs">
        {err ? (
          <span className="text-corp-danger">{err}</span>
        ) : msg ? (
          <span className="text-corp-muted">{msg}</span>
        ) : null}
      </div>
      <button
        type="button"
        className="jsp-btn-primary"
        onClick={onSave}
        disabled={saving || !dirty}
      >
        {saving ? "Saving..." : dirty ? "Save" : "Saved"}
      </button>
    </div>
  );
}

// ---------- Job Preferences -------------------------------------------------

type JobPreferences = {
  id: number;
  salary_currency: string;
  salary_preferred_target?: number | null;
  salary_acceptable_min?: number | null;
  salary_unacceptable_below?: number | null;
  total_comp_preferred_target?: number | null;
  total_comp_acceptable_min?: number | null;
  experience_level_preferred?: string | null;
  experience_levels_acceptable?: string[] | null;
  experience_levels_unacceptable?: string[] | null;
  remote_policy_preferred?: string | null;
  remote_policies_acceptable?: string[] | null;
  remote_policies_unacceptable?: string[] | null;
  max_commute_minutes_preferred?: number | null;
  max_commute_minutes_acceptable?: number | null;
  willing_to_relocate: boolean;
  relocation_notes?: string | null;
  travel_percent_preferred?: number | null;
  travel_percent_acceptable_max?: number | null;
  travel_percent_unacceptable_above?: number | null;
  hours_per_week_preferred?: number | null;
  hours_per_week_acceptable_max?: number | null;
  overtime_acceptable: boolean;
  employment_types_preferred?: string[] | null;
  employment_types_acceptable?: string[] | null;
  employment_types_unacceptable?: string[] | null;
  equity_preference?: string | null;
  benefits_required?: string[] | null;
  benefits_preferred?: string[] | null;
  earliest_start_date?: string | null;
  latest_start_date?: string | null;
  notice_period_weeks?: number | null;
  dealbreakers_notes?: string | null;
  dream_job_notes?: string | null;
};

function JobPreferencesPanel() {
  const [data, setData] = useState<JobPreferences | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api
      .get<JobPreferences | null>("/api/v1/preferences/job")
      .then((d) => {
        setData(
          d ?? {
            id: 0,
            salary_currency: "USD",
            willing_to_relocate: false,
            overtime_acceptable: false,
          },
        );
        setLoaded(true);
      })
      .catch((e) => {
        setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
        setLoaded(true);
      });
  }, []);

  function set<K extends keyof JobPreferences>(k: K, v: JobPreferences[K]) {
    setData((prev) => (prev ? { ...prev, [k]: v } : prev));
    setDirty(true);
    setMsg(null);
  }

  async function save() {
    if (!data) return;
    setSaving(true);
    setErr(null);
    try {
      const body = { ...data };
      delete (body as Partial<JobPreferences>).id;
      const out = await api.put<JobPreferences>("/api/v1/preferences/job", body);
      setData(out);
      setDirty(false);
      setMsg("Saved.");
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (!loaded || !data) {
    return <p className="text-sm text-corp-muted">Loading...</p>;
  }

  return (
    <div className="jsp-card p-5 space-y-4">
      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Compensation
        </h3>
        <div className="grid grid-cols-4 gap-3">
          <div>
            <label className="jsp-label">Currency</label>
            <input
              className="jsp-input"
              value={data.salary_currency ?? "USD"}
              onChange={(e) => set("salary_currency", e.target.value.toUpperCase())}
            />
          </div>
          <div>
            <label className="jsp-label">Target salary</label>
            <input
              className="jsp-input"
              type="number"
              value={data.salary_preferred_target ?? ""}
              onChange={(e) => set("salary_preferred_target", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Acceptable min</label>
            <input
              className="jsp-input"
              type="number"
              value={data.salary_acceptable_min ?? ""}
              onChange={(e) => set("salary_acceptable_min", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Hard floor</label>
            <input
              className="jsp-input"
              type="number"
              value={data.salary_unacceptable_below ?? ""}
              onChange={(e) => set("salary_unacceptable_below", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Target total comp</label>
            <input
              className="jsp-input"
              type="number"
              value={data.total_comp_preferred_target ?? ""}
              onChange={(e) => set("total_comp_preferred_target", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Acceptable total comp</label>
            <input
              className="jsp-input"
              type="number"
              value={data.total_comp_acceptable_min ?? ""}
              onChange={(e) => set("total_comp_acceptable_min", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Equity preference</label>
            <input
              className="jsp-input"
              value={data.equity_preference ?? ""}
              onChange={(e) => set("equity_preference", e.target.value || null)}
              placeholder="required / welcome / neutral"
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Role shape
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Experience level preferred</label>
            <input
              className="jsp-input"
              value={data.experience_level_preferred ?? ""}
              onChange={(e) => set("experience_level_preferred", e.target.value || null)}
              placeholder="senior"
            />
          </div>
          <div>
            <label className="jsp-label">Acceptable levels</label>
            <input
              className="jsp-input"
              value={listToCsv(data.experience_levels_acceptable)}
              onChange={(e) => set("experience_levels_acceptable", csvToList(e.target.value))}
              placeholder="mid, senior, staff"
            />
          </div>
          <div>
            <label className="jsp-label">Unacceptable levels</label>
            <input
              className="jsp-input"
              value={listToCsv(data.experience_levels_unacceptable)}
              onChange={(e) => set("experience_levels_unacceptable", csvToList(e.target.value))}
              placeholder="junior"
            />
          </div>
          <div>
            <label className="jsp-label">Remote policy preferred</label>
            <input
              className="jsp-input"
              value={data.remote_policy_preferred ?? ""}
              onChange={(e) => set("remote_policy_preferred", e.target.value || null)}
              placeholder="remote"
            />
          </div>
          <div>
            <label className="jsp-label">Acceptable remote</label>
            <input
              className="jsp-input"
              value={listToCsv(data.remote_policies_acceptable)}
              onChange={(e) => set("remote_policies_acceptable", csvToList(e.target.value))}
              placeholder="remote, hybrid"
            />
          </div>
          <div>
            <label className="jsp-label">Unacceptable remote</label>
            <input
              className="jsp-input"
              value={listToCsv(data.remote_policies_unacceptable)}
              onChange={(e) => set("remote_policies_unacceptable", csvToList(e.target.value))}
              placeholder="onsite"
            />
          </div>
          <div>
            <label className="jsp-label">Employment types preferred</label>
            <input
              className="jsp-input"
              value={listToCsv(data.employment_types_preferred)}
              onChange={(e) => set("employment_types_preferred", csvToList(e.target.value))}
              placeholder="full_time"
            />
          </div>
          <div>
            <label className="jsp-label">Employment acceptable</label>
            <input
              className="jsp-input"
              value={listToCsv(data.employment_types_acceptable)}
              onChange={(e) => set("employment_types_acceptable", csvToList(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Employment unacceptable</label>
            <input
              className="jsp-input"
              value={listToCsv(data.employment_types_unacceptable)}
              onChange={(e) => set("employment_types_unacceptable", csvToList(e.target.value))}
              placeholder="contract"
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Location & schedule
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Commute preferred (min)</label>
            <input
              type="number"
              className="jsp-input"
              value={data.max_commute_minutes_preferred ?? ""}
              onChange={(e) => set("max_commute_minutes_preferred", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Commute acceptable (min)</label>
            <input
              type="number"
              className="jsp-input"
              value={data.max_commute_minutes_acceptable ?? ""}
              onChange={(e) => set("max_commute_minutes_acceptable", numOrNull(e.target.value))}
            />
          </div>
          <div className="flex items-end gap-2">
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={data.willing_to_relocate}
                onChange={(e) => set("willing_to_relocate", e.target.checked)}
              />
              Willing to relocate
            </label>
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Relocation notes</label>
            <input
              className="jsp-input"
              value={data.relocation_notes ?? ""}
              onChange={(e) => set("relocation_notes", e.target.value || null)}
              placeholder="Open to EU; not TX or FL."
            />
          </div>
          <div>
            <label className="jsp-label">Travel preferred (%)</label>
            <input
              type="number"
              className="jsp-input"
              value={data.travel_percent_preferred ?? ""}
              onChange={(e) => set("travel_percent_preferred", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Travel acceptable max (%)</label>
            <input
              type="number"
              className="jsp-input"
              value={data.travel_percent_acceptable_max ?? ""}
              onChange={(e) => set("travel_percent_acceptable_max", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Travel unacceptable above (%)</label>
            <input
              type="number"
              className="jsp-input"
              value={data.travel_percent_unacceptable_above ?? ""}
              onChange={(e) => set("travel_percent_unacceptable_above", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Hours/week preferred</label>
            <input
              type="number"
              className="jsp-input"
              value={data.hours_per_week_preferred ?? ""}
              onChange={(e) => set("hours_per_week_preferred", numOrNull(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Hours/week max</label>
            <input
              type="number"
              className="jsp-input"
              value={data.hours_per_week_acceptable_max ?? ""}
              onChange={(e) => set("hours_per_week_acceptable_max", numOrNull(e.target.value))}
            />
          </div>
          <div className="flex items-end gap-2">
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={data.overtime_acceptable}
                onChange={(e) => set("overtime_acceptable", e.target.checked)}
              />
              Overtime OK
            </label>
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Benefits, start dates, & notes
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Earliest start</label>
            <input
              type="date"
              className="jsp-input"
              value={data.earliest_start_date ?? ""}
              onChange={(e) => set("earliest_start_date", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Latest start</label>
            <input
              type="date"
              className="jsp-input"
              value={data.latest_start_date ?? ""}
              onChange={(e) => set("latest_start_date", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Notice period (weeks)</label>
            <input
              type="number"
              className="jsp-input"
              value={data.notice_period_weeks ?? ""}
              onChange={(e) => set("notice_period_weeks", numOrNull(e.target.value))}
            />
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Required benefits (comma-separated)</label>
            <input
              className="jsp-input"
              value={listToCsv(data.benefits_required)}
              onChange={(e) => set("benefits_required", csvToList(e.target.value))}
              placeholder="health insurance, 401k match, 20 days PTO"
            />
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Nice-to-have benefits</label>
            <input
              className="jsp-input"
              value={listToCsv(data.benefits_preferred)}
              onChange={(e) => set("benefits_preferred", csvToList(e.target.value))}
              placeholder="learning stipend, home office, sabbatical"
            />
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Dealbreakers</label>
            <textarea
              className="jsp-input min-h-[80px]"
              value={data.dealbreakers_notes ?? ""}
              onChange={(e) => set("dealbreakers_notes", e.target.value || null)}
              placeholder="No on-call rotations. No surveillance tooling."
            />
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Dream job notes</label>
            <textarea
              className="jsp-input min-h-[80px]"
              value={data.dream_job_notes ?? ""}
              onChange={(e) => set("dream_job_notes", e.target.value || null)}
              placeholder="Small distributed team, early-stage infra product, founder-led."
            />
          </div>
        </div>
      </section>

      <SaveBar dirty={dirty} saving={saving} err={err} msg={msg} onSave={save} />
    </div>
  );
}

// ---------- Work Authorization ---------------------------------------------

type WorkAuthorization = {
  id: number;
  current_country?: string | null;
  current_location_city?: string | null;
  current_location_region?: string | null;
  citizenship_countries?: string[] | null;
  work_authorization_status?: string | null;
  visa_type?: string | null;
  visa_issued_date?: string | null;
  visa_expires_date?: string | null;
  visa_sponsorship_required_now: boolean;
  visa_sponsorship_required_future: boolean;
  relocation_countries_acceptable?: string[] | null;
  security_clearance_level?: string | null;
  security_clearance_active: boolean;
  security_clearance_notes?: string | null;
  export_control_considerations?: string | null;
};

function WorkAuthorizationPanel() {
  const [data, setData] = useState<WorkAuthorization | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api
      .get<WorkAuthorization | null>("/api/v1/preferences/authorization")
      .then((d) => {
        setData(
          d ?? {
            id: 0,
            visa_sponsorship_required_now: false,
            visa_sponsorship_required_future: false,
            security_clearance_active: false,
          },
        );
        setLoaded(true);
      })
      .catch((e) => {
        setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
        setLoaded(true);
      });
  }, []);

  function set<K extends keyof WorkAuthorization>(k: K, v: WorkAuthorization[K]) {
    setData((prev) => (prev ? { ...prev, [k]: v } : prev));
    setDirty(true);
    setMsg(null);
  }

  async function save() {
    if (!data) return;
    setSaving(true);
    setErr(null);
    try {
      const body = { ...data };
      delete (body as Partial<WorkAuthorization>).id;
      const out = await api.put<WorkAuthorization>(
        "/api/v1/preferences/authorization",
        body,
      );
      setData(out);
      setDirty(false);
      setMsg("Saved.");
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setErr(
        e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (!loaded || !data) {
    return <p className="text-sm text-corp-muted">Loading...</p>;
  }

  return (
    <div className="jsp-card p-5 space-y-4">
      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Location
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Country</label>
            <input
              className="jsp-input"
              value={data.current_country ?? ""}
              onChange={(e) => set("current_country", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">City</label>
            <input
              className="jsp-input"
              value={data.current_location_city ?? ""}
              onChange={(e) => set("current_location_city", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">State / region</label>
            <input
              className="jsp-input"
              value={data.current_location_region ?? ""}
              onChange={(e) => set("current_location_region", e.target.value || null)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Authorization
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Citizenship(s)</label>
            <input
              className="jsp-input"
              value={listToCsv(data.citizenship_countries)}
              onChange={(e) => set("citizenship_countries", csvToList(e.target.value))}
              placeholder="US, CA"
            />
          </div>
          <div>
            <label className="jsp-label">Work auth status</label>
            <input
              className="jsp-input"
              value={data.work_authorization_status ?? ""}
              onChange={(e) => set("work_authorization_status", e.target.value || null)}
              placeholder="citizen / permanent_resident / visa"
            />
          </div>
          <div>
            <label className="jsp-label">Visa type</label>
            <input
              className="jsp-input"
              value={data.visa_type ?? ""}
              onChange={(e) => set("visa_type", e.target.value || null)}
              placeholder="H-1B, OPT, TN, etc."
            />
          </div>
          <div>
            <label className="jsp-label">Visa issued</label>
            <input
              type="date"
              className="jsp-input"
              value={data.visa_issued_date ?? ""}
              onChange={(e) => set("visa_issued_date", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Visa expires</label>
            <input
              type="date"
              className="jsp-input"
              value={data.visa_expires_date ?? ""}
              onChange={(e) => set("visa_expires_date", e.target.value || null)}
            />
          </div>
          <div className="flex flex-col gap-1 justify-end text-sm">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={data.visa_sponsorship_required_now}
                onChange={(e) => set("visa_sponsorship_required_now", e.target.checked)}
              />
              Needs sponsorship now
            </label>
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={data.visa_sponsorship_required_future}
                onChange={(e) => set("visa_sponsorship_required_future", e.target.checked)}
              />
              Will need sponsorship
            </label>
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Relocation countries (comma-separated)</label>
            <input
              className="jsp-input"
              value={listToCsv(data.relocation_countries_acceptable)}
              onChange={(e) => set("relocation_countries_acceptable", csvToList(e.target.value))}
              placeholder="US, CA, UK, DE"
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Clearance
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Level</label>
            <input
              className="jsp-input"
              value={data.security_clearance_level ?? ""}
              onChange={(e) => set("security_clearance_level", e.target.value || null)}
              placeholder="Secret / TS / TS-SCI"
            />
          </div>
          <div className="flex items-end">
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={data.security_clearance_active}
                onChange={(e) => set("security_clearance_active", e.target.checked)}
              />
              Currently active
            </label>
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Clearance notes</label>
            <input
              className="jsp-input"
              value={data.security_clearance_notes ?? ""}
              onChange={(e) => set("security_clearance_notes", e.target.value || null)}
            />
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Export-control considerations</label>
            <input
              className="jsp-input"
              value={data.export_control_considerations ?? ""}
              onChange={(e) => set("export_control_considerations", e.target.value || null)}
              placeholder="ITAR, EAR, etc."
            />
          </div>
        </div>
      </section>

      <SaveBar dirty={dirty} saving={saving} err={err} msg={msg} onSave={save} />
    </div>
  );
}

// ---------- Criteria list ---------------------------------------------------

type Criterion = {
  id: number;
  category: string;
  value: string;
  tier: "preferred" | "acceptable" | "unacceptable";
  weight?: number | null;
  notes?: string | null;
};

function CriteriaPanel() {
  const [items, setItems] = useState<Criterion[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setItems(await api.get<Criterion[]>("/api/v1/preferences/criteria"));
    } catch (e) {
      setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function remove(id: number) {
    await api.delete(`/api/v1/preferences/criteria/${id}`);
    await refresh();
  }

  return (
    <div className="jsp-card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm uppercase tracking-wider text-corp-muted">Criteria list</h3>
          <p className="text-[11px] text-corp-muted mt-1">
            Granular preferred / acceptable / unacceptable tags across industry,
            role, technology, company size, mission, anything else. The Companion
            and job-fit-scorer weight these into its reads of each posting.
          </p>
        </div>
        <button className="jsp-btn-primary" type="button" onClick={() => setAdding(true)}>
          + New criterion
        </button>
      </div>
      {err ? <div className="text-xs text-corp-danger">{err}</div> : null}
      {adding ? (
        <CriterionForm
          onCancel={() => setAdding(false)}
          onSaved={async () => {
            setAdding(false);
            await refresh();
          }}
        />
      ) : null}
      {loading ? (
        <p className="text-sm text-corp-muted">Loading...</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-corp-muted">No criteria yet.</p>
      ) : (
        <ul className="divide-y divide-corp-border">
          {items.map((c) => (
            <li key={c.id} className="flex items-center gap-3 py-1.5">
              <span className="text-[10px] uppercase tracking-wider text-corp-muted w-20 shrink-0">
                {c.category}
              </span>
              <span className="text-sm flex-1 truncate">{c.value}</span>
              <span
                className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${
                  c.tier === "preferred"
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                    : c.tier === "acceptable"
                      ? "bg-corp-surface2 text-corp-muted border-corp-border"
                      : "bg-corp-danger/20 text-corp-danger border-corp-danger/40"
                }`}
              >
                {c.tier}
              </span>
              {c.notes ? (
                <span
                  className="text-[11px] text-corp-muted truncate max-w-[16ch]"
                  title={c.notes}
                >
                  {c.notes}
                </span>
              ) : null}
              <button
                className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                onClick={() => remove(c.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CriterionForm({
  onCancel,
  onSaved,
}: {
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [category, setCategory] = useState("");
  const [value, setValue] = useState("");
  const [tier, setTier] = useState<Criterion["tier"]>("preferred");
  const [weight, setWeight] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!category.trim() || !value.trim()) {
      setErr("Category and value are required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await api.post("/api/v1/preferences/criteria", {
        category: category.trim(),
        value: value.trim(),
        tier,
        weight: weight ? Number(weight) : null,
        notes: notes || null,
      });
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="jsp-card p-3 bg-corp-surface2 grid grid-cols-[120px_1fr_140px_80px_auto] gap-2 items-end"
    >
      <div>
        <label className="jsp-label">Category</label>
        <input
          className="jsp-input"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          placeholder="industry / role / tech"
        />
      </div>
      <div>
        <label className="jsp-label">Value</label>
        <input
          className="jsp-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="GraphQL"
        />
      </div>
      <div>
        <label className="jsp-label">Tier</label>
        <select
          className="jsp-input"
          value={tier}
          onChange={(e) => setTier(e.target.value as Criterion["tier"])}
        >
          <option value="preferred">preferred</option>
          <option value="acceptable">acceptable</option>
          <option value="unacceptable">unacceptable</option>
        </select>
      </div>
      <div>
        <label className="jsp-label">Weight</label>
        <input
          type="number"
          className="jsp-input"
          value={weight}
          onChange={(e) => setWeight(e.target.value)}
          placeholder="1-5"
        />
      </div>
      <div className="flex gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary" disabled={saving}>
          {saving ? "..." : "Add"}
        </button>
      </div>
      <div className="col-span-5">
        <label className="jsp-label">Notes (optional)</label>
        <input
          className="jsp-input"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Why this matters, caveats, etc."
        />
        {err ? <div className="text-xs text-corp-danger mt-1">{err}</div> : null}
      </div>
    </form>
  );
}

// ---------- Demographics ----------------------------------------------------

type Demographics = {
  id: number;
  preferred_name?: string | null;
  legal_first_name?: string | null;
  legal_middle_name?: string | null;
  legal_last_name?: string | null;
  legal_suffix?: string | null;
  pronouns?: string | null;
  pronouns_self_describe?: string | null;
  gender_identity?: string | null;
  gender_self_describe?: string | null;
  sex_assigned_at_birth?: string | null;
  transgender_identification?: string | null;
  sexual_orientation?: string | null;
  sexual_orientation_self_describe?: string | null;
  race_ethnicity?: string[] | null;
  ethnicity_self_describe?: string | null;
  veteran_status?: string | null;
  disability_status?: string | null;
  disability_notes?: string | null;
  accommodation_needs?: string | null;
  date_of_birth?: string | null;
  age_bracket?: string | null;
  first_generation_college_student?: string | null;
};

function DemographicsPanel() {
  const [data, setData] = useState<Demographics | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api
      .get<Demographics | null>("/api/v1/preferences/demographics")
      .then((d) => {
        setData(d ?? { id: 0 });
        setLoaded(true);
      })
      .catch((e) => {
        setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
        setLoaded(true);
      });
  }, []);

  function set<K extends keyof Demographics>(k: K, v: Demographics[K]) {
    setData((prev) => (prev ? { ...prev, [k]: v } : prev));
    setDirty(true);
    setMsg(null);
  }

  async function save() {
    if (!data) return;
    setSaving(true);
    setErr(null);
    try {
      const body = { ...data };
      delete (body as Partial<Demographics>).id;
      const out = await api.put<Demographics>(
        "/api/v1/preferences/demographics",
        body,
      );
      setData(out);
      setDirty(false);
      setMsg("Saved.");
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setErr(e instanceof ApiError ? `Save failed (HTTP ${e.status}).` : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  if (!loaded || !data) {
    return <p className="text-sm text-corp-muted">Loading...</p>;
  }

  return (
    <div className="jsp-card p-5 space-y-4">
      <p className="text-[11px] text-corp-muted bg-corp-surface2 p-2 rounded border border-corp-border">
        Voluntary self-identification. The Companion never receives this as free
        text — only templated placeholder substitution during application-autofill,
        and only for fields you&apos;ve opted to share.
      </p>
      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Name & pronouns
        </h3>
        <div className="grid grid-cols-4 gap-3">
          <div>
            <label className="jsp-label">Preferred name</label>
            <input
              className="jsp-input"
              value={data.preferred_name ?? ""}
              onChange={(e) => set("preferred_name", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Legal first</label>
            <input
              className="jsp-input"
              value={data.legal_first_name ?? ""}
              onChange={(e) => set("legal_first_name", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Middle</label>
            <input
              className="jsp-input"
              value={data.legal_middle_name ?? ""}
              onChange={(e) => set("legal_middle_name", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Legal last</label>
            <input
              className="jsp-input"
              value={data.legal_last_name ?? ""}
              onChange={(e) => set("legal_last_name", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Suffix</label>
            <input
              className="jsp-input"
              value={data.legal_suffix ?? ""}
              onChange={(e) => set("legal_suffix", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Pronouns</label>
            <input
              className="jsp-input"
              value={data.pronouns ?? ""}
              onChange={(e) => set("pronouns", e.target.value || null)}
              placeholder="she/her, he/him, they/them…"
            />
          </div>
          <div className="col-span-2">
            <label className="jsp-label">Self-described (optional)</label>
            <input
              className="jsp-input"
              value={data.pronouns_self_describe ?? ""}
              onChange={(e) => set("pronouns_self_describe", e.target.value || null)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Identity
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Gender identity</label>
            <input
              className="jsp-input"
              value={data.gender_identity ?? ""}
              onChange={(e) => set("gender_identity", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Self-describe</label>
            <input
              className="jsp-input"
              value={data.gender_self_describe ?? ""}
              onChange={(e) => set("gender_self_describe", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Sex at birth</label>
            <input
              className="jsp-input"
              value={data.sex_assigned_at_birth ?? ""}
              onChange={(e) => set("sex_assigned_at_birth", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Transgender identification</label>
            <input
              className="jsp-input"
              value={data.transgender_identification ?? ""}
              onChange={(e) => set("transgender_identification", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Sexual orientation</label>
            <input
              className="jsp-input"
              value={data.sexual_orientation ?? ""}
              onChange={(e) => set("sexual_orientation", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Self-describe</label>
            <input
              className="jsp-input"
              value={data.sexual_orientation_self_describe ?? ""}
              onChange={(e) => set("sexual_orientation_self_describe", e.target.value || null)}
            />
          </div>
          <div className="col-span-2">
            <label className="jsp-label">Race / ethnicity (comma-separated)</label>
            <input
              className="jsp-input"
              value={listToCsv(data.race_ethnicity)}
              onChange={(e) => set("race_ethnicity", csvToList(e.target.value))}
            />
          </div>
          <div>
            <label className="jsp-label">Self-describe</label>
            <input
              className="jsp-input"
              value={data.ethnicity_self_describe ?? ""}
              onChange={(e) => set("ethnicity_self_describe", e.target.value || null)}
            />
          </div>
        </div>
      </section>

      <section>
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
          Other
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="jsp-label">Veteran status</label>
            <input
              className="jsp-input"
              value={data.veteran_status ?? ""}
              onChange={(e) => set("veteran_status", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Disability status</label>
            <input
              className="jsp-input"
              value={data.disability_status ?? ""}
              onChange={(e) => set("disability_status", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">First-gen college student</label>
            <input
              className="jsp-input"
              value={data.first_generation_college_student ?? ""}
              onChange={(e) => set("first_generation_college_student", e.target.value || null)}
            />
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Disability notes</label>
            <input
              className="jsp-input"
              value={data.disability_notes ?? ""}
              onChange={(e) => set("disability_notes", e.target.value || null)}
            />
          </div>
          <div className="col-span-3">
            <label className="jsp-label">Accommodation needs</label>
            <textarea
              className="jsp-input min-h-[60px]"
              value={data.accommodation_needs ?? ""}
              onChange={(e) => set("accommodation_needs", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Date of birth</label>
            <input
              type="date"
              className="jsp-input"
              value={data.date_of_birth ?? ""}
              onChange={(e) => set("date_of_birth", e.target.value || null)}
            />
          </div>
          <div>
            <label className="jsp-label">Age bracket</label>
            <input
              className="jsp-input"
              value={data.age_bracket ?? ""}
              onChange={(e) => set("age_bracket", e.target.value || null)}
              placeholder="25-34"
            />
          </div>
        </div>
      </section>

      <SaveBar dirty={dirty} saving={saving} err={err} msg={msg} onSave={save} />
    </div>
  );
}
