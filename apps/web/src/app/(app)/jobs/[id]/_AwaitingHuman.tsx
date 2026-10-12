"use client";

// Shown only while a job is at status=awaiting_human — the problem an
// external agent (MCP request_human_help) needs a person for. Editable
// so the user can add context; nothing in the app acts on it.

import { useEffect, useState } from "react";

export function AwaitingHumanBox({
  reason,
  saving,
  onSave,
}: {
  reason: string | null | undefined;
  saving: boolean;
  onSave: (reason: string | null) => void;
}) {
  const [text, setText] = useState(reason ?? "");
  useEffect(() => setText(reason ?? ""), [reason]);
  const dirty = text.trim() !== (reason ?? "").trim();

  return (
    <section className="jsp-card p-3 mb-4 border-l-4 border-l-green-500 bg-green-500/5 space-y-2">
      <div className="text-sm font-medium text-green-300">Awaiting human — what&apos;s needed</div>
      <textarea
        className="jsp-input text-sm min-h-[70px]"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="No problem description yet — an agent sets this with request_human_help, or write your own."
        disabled={saving}
      />
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-corp-muted flex-1">
          Change the status when it&apos;s handled. This note is kept but only shows in this status.
        </span>
        {dirty ? (
          <button
            type="button"
            className="jsp-btn-primary text-xs"
            disabled={saving}
            onClick={() => onSave(text.trim() || null)}
          >
            Save
          </button>
        ) : null}
      </div>
    </section>
  );
}
