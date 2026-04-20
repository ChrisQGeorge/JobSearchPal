"use client";

import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { ComingSoon } from "@/components/ComingSoon";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();

  async function logout() {
    await api.post("/api/v1/auth/logout");
    router.replace("/login");
  }

  return (
    <PageShell
      title="Settings"
      subtitle="App configuration, API keys, themes, personas, and account."
      actions={
        <button className="jsp-btn-ghost text-corp-danger border-corp-danger/40" onClick={logout}>
          Log out
        </button>
      }
    >
      <div className="space-y-4">
        <ComingSoon
          title="API Credentials"
          description="Store an encrypted Anthropic API key (AES-256-GCM at rest). Test connection. Set per-skill model overrides."
          plannedFor="R0+"
        />
        <ComingSoon
          title="AI Persona"
          description="Pick from built-in personas or define custom ones with name, tone descriptors, system prompt, and avatar."
          plannedFor="R5"
        />
        <ComingSoon
          title="Data Export / Reset"
          description="JSON + SQL dump export. Credential rotation. Full data purge."
          plannedFor="R0+"
        />
      </div>
    </PageShell>
  );
}
