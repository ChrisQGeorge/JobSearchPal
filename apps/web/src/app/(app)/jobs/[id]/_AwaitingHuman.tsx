"use client";

// Shown only while a job is at status=awaiting_human — the problem an
// external agent (MCP request_human_help) needs a person for, and, once
// there is a problem written, the person's resolution, which the agent
// reads (get_job) before trying again. Nothing in the app acts on either.

import { useEffect, useState } from "react";

export function AwaitingHumanBox({
  reason,
  resolution,
  saving,
  onSave,
}: {
  reason: string | null | undefined;
  resolution: string | null | undefined;
  saving: boolean;
  onSave: (v: { awaiting_human_reason: string | null; awaiting_human_resolution: string | null }) => void;
}) {
  const [text, setText] = useState(reason ?? "");
  const [res, setRes] = useState(resolution ?? "");
  useEffect(() => setText(reason ?? ""), [reason]);
  useEffect(() => setRes(resolution ?? ""), [resolution]);
  const dirty =
    text.trim() !== (reason ?? "").trim() || res.trim() !== (resolution ?? "").trim();
  const hasProblem = text.trim().length > 0;

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
      {hasProblem ? (
        <>
          <div className="text-sm font-medium text-green-300 pt-1">Resolution</div>
          <textarea
            className="jsp-input text-sm min-h-[70px]"
            value={res}
            onChange={(e) => setRes(e.target.value)}
            placeholder="How you handled it / what the agent should do next time (e.g. 'Portfolio link: https://…', 'Solved the CAPTCHA — retry the apply'). The agent reads this before trying again."
            disabled={saving}
          />
        </>
      ) : null}
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-corp-muted flex-1">
          Write the resolution, then change the status so the agent can try again. Both notes are
          kept but only show in this status.
        </span>
        {dirty ? (
          <button
            type="button"
            className="jsp-btn-primary text-xs"
            disabled={saving}
            onClick={() =>
              onSave({
                awaiting_human_reason: text.trim() || null,
                awaiting_human_resolution: res.trim() || null,
              })
            }
          >
            Save
          </button>
        ) : null}
      </div>
    </section>
  );
}
