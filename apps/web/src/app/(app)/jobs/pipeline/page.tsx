"use client";

import { useState } from "react";
import { PageShell } from "@/components/PageShell";
import { ApplyPanel } from "./_panels/ApplyPanel";
import { ReviewPanel } from "./_panels/ReviewPanel";

type Tab = "review" | "apply";

const TABS: { key: Tab; label: string }[] = [
  { key: "review", label: "Review" },
  { key: "apply", label: "Apply" },
];

export default function PipelinePage() {
  const [tab, setTab] = useState<Tab>("review");
  return (
    <PageShell
      title="Review & Apply"
      subtitle="Triage fresh jobs in Review, then work through the ones you flagged as interested in Apply."
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

      {tab === "review" && <ReviewPanel />}
      {tab === "apply" && <ApplyPanel />}
    </PageShell>
  );
}
