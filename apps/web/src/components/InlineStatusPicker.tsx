"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { JOB_STATUSES, type JobStatus } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";

/**
 * A compact in-place status picker for the Job Tracker table. Clicking the
 * pill reveals a dropdown; selecting a new status PUTs it and updates the
 * row optimistically via the onChange callback.
 *
 * Clicks are stop-propagated so the surrounding row-click navigation
 * doesn't fire while the user is editing.
 */
export function InlineStatusPicker({
  jobId,
  status,
  onChange,
}: {
  jobId: number;
  status: JobStatus;
  onChange: (next: JobStatus) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  async function commit(next: JobStatus) {
    if (next === status) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await api.put(`/api/v1/jobs/${jobId}`, { status: next });
      onChange(next);
    } catch {
      /* rollback: keep the old value */
    } finally {
      setBusy(false);
      setEditing(false);
    }
  }

  if (editing) {
    return (
      <select
        className="jsp-input text-xs py-0.5 px-1 uppercase tracking-wider"
        autoFocus
        value={status}
        disabled={busy}
        onClick={(e) => e.stopPropagation()}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setEditing(false);
        }}
        onChange={(e) => commit(e.target.value as JobStatus)}
      >
        {JOB_STATUSES.map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
    );
  }

  return (
    <button
      type="button"
      disabled={busy}
      onClick={(e) => {
        e.stopPropagation();
        setEditing(true);
      }}
      title="Click to change status"
      className="hover:ring-1 hover:ring-corp-accent/40 rounded"
    >
      <StatusBadge status={status} />
    </button>
  );
}
