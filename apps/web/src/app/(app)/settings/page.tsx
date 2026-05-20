"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { api } from "@/lib/api";
import {
  ApiKeysPanel,
  ClaudeAuthPanel,
  DataIoPanel,
  PersonaManager,
} from "./_panels/SettingsPanels";
import {
  CriteriaPanel,
  DemographicsPanel,
  JobPreferencesPanel,
  ResumeProfilePanel,
  WorkAuthorizationPanel,
} from "./_panels/PreferencesPanels";

type Tab =
  | "resume"
  | "job"
  | "auth"
  | "criteria"
  | "demographics"
  | "claude-auth"
  | "api-keys"
  | "personas"
  | "data-io";

const TABS: { key: Tab; label: string }[] = [
  // Identity / preferences first — these are about you, not the app.
  { key: "resume", label: "Resume Profile" },
  { key: "job", label: "Job Preferences" },
  { key: "auth", label: "Work Authorization" },
  { key: "criteria", label: "Criteria List" },
  { key: "demographics", label: "Demographics" },
  // App-level config follows.
  { key: "claude-auth", label: "Claude Auth" },
  { key: "api-keys", label: "API Keys" },
  { key: "personas", label: "Personas" },
  { key: "data-io", label: "Data Export / Import" },
];

export default function SettingsPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("resume");

  async function logout() {
    await api.post("/api/v1/auth/logout");
    router.replace("/login");
  }

  return (
    <PageShell
      title="Settings"
      subtitle="Who you are, what you want, and how the app talks to Claude."
      actions={
        <button
          className="jsp-btn-ghost text-corp-danger border-corp-danger/40"
          onClick={logout}
        >
          Log out
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

      {tab === "resume" && <ResumeProfilePanel />}
      {tab === "job" && <JobPreferencesPanel />}
      {tab === "auth" && <WorkAuthorizationPanel />}
      {tab === "criteria" && <CriteriaPanel />}
      {tab === "demographics" && <DemographicsPanel />}
      {tab === "claude-auth" && <ClaudeAuthPanel />}
      {tab === "api-keys" && <ApiKeysPanel />}
      {tab === "personas" && <PersonaManager />}
      {tab === "data-io" && <DataIoPanel />}
    </PageShell>
  );
}
