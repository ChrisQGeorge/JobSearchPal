"use client";

// Kicks off a Companion conversation focused on one history entry.
// Posts to /api/v1/companion/conversations/analyze-entity, then routes
// the user into the /companion page with the new conversation already
// active. The chat persists like any other CompanionConversation so
// the user can come back to it later from the Companion sidebar.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

type AnalyzeEntityType =
  | "work"
  | "education"
  | "certification"
  | "publication"
  | "achievement"
  | "volunteer"
  | "project"
  | "custom";

export function AnalyzeEntityButton({
  entityType,
  entityId,
  size = "xs",
  variant = "ghost",
}: {
  entityType: AnalyzeEntityType;
  entityId: number;
  size?: "xs" | "sm";
  variant?: "ghost" | "primary";
}) {
  const router = useRouter();
  const [running, setRunning] = useState(false);

  async function go() {
    setRunning(true);
    try {
      const conv = await api.post<{ id: number; title?: string | null }>(
        "/api/v1/companion/conversations/analyze-entity",
        { entity_type: entityType, entity_id: entityId },
      );
      // The /companion page already supports ?conv=<id> to deep-link
      // into a specific conversation. Navigate there so the user lands
      // in the chat with the Companion's first message already loaded.
      router.push(`/companion?conv=${conv.id}`);
    } catch (e) {
      const detail =
        e instanceof ApiError &&
        typeof e.detail === "object" &&
        e.detail !== null &&
        "detail" in (e.detail as Record<string, unknown>)
          ? String((e.detail as { detail: unknown }).detail)
          : e instanceof ApiError
            ? `HTTP ${e.status}`
            : "Analyze failed.";
      alert(`Couldn't start analysis: ${detail}`);
      setRunning(false);
    }
  }

  const cls =
    variant === "primary"
      ? `jsp-btn-primary text-${size}`
      : `jsp-btn-ghost text-${size}`;
  return (
    <button
      type="button"
      className={cls}
      onClick={go}
      disabled={running}
      title="Start a focused Companion chat to enrich this entry — the Companion will look at your skills and ask questions to help fill it out."
    >
      {running ? "Opening…" : "Analyze"}
    </button>
  );
}
