"use client";

import { useState } from "react";
import { PageShell } from "@/components/PageShell";
import { CoverLetterLibraryPanel } from "./_panels/CoverLetterLibraryPanel";
import { DocumentsPanel } from "./_panels/DocumentsPanel";
import { SamplesPanel } from "./_panels/SamplesPanel";

type Tab = "documents" | "cover-letters" | "samples";

const TABS: { key: Tab; label: string }[] = [
  { key: "documents", label: "Documents" },
  { key: "cover-letters", label: "Cover Letter Library" },
  { key: "samples", label: "Writing Samples" },
];

export default function StudioPage() {
  const [tab, setTab] = useState<Tab>("documents");
  return (
    <PageShell
      title="Document Studio"
      subtitle="Resumes, cover letters, and the reference corpus that keeps drafts in your voice."
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

      {tab === "documents" && <DocumentsPanel />}
      {tab === "cover-letters" && <CoverLetterLibraryPanel />}
      {tab === "samples" && <SamplesPanel />}
    </PageShell>
  );
}
