"use client";

// Right-side panel for analyze-entity conversations. Shows the current
// state of the entity being discussed and re-fetches every ~6 seconds
// so the user can watch the Companion's edits land live.

import { useEffect, useState } from "react";
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

const LABEL_FOR: Record<AnalyzeEntityType, string> = {
  work: "Work Experience",
  education: "Education",
  certification: "Certification",
  publication: "Publication",
  achievement: "Achievement",
  volunteer: "Volunteer Work",
  project: "Project",
  custom: "Custom Event",
};

// Columns the user doesn't care about visually — same skip-list the
// backend uses when building the prompt. Sorting + grouping helpers
// could come later; for now alphabetic but with id/timestamps hidden.
const HIDDEN_KEYS = new Set([
  "id",
  "user_id",
  "created_at",
  "updated_at",
  "deleted_at",
]);

type EntityRow = Record<string, unknown>;

const REFRESH_MS = 6_000;

export function AnalyzeEntityDetailPanel({
  entityType,
  entityId,
}: {
  entityType: AnalyzeEntityType;
  entityId: number;
}) {
  const [entity, setEntity] = useState<EntityRow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const url = `/api/v1/history/entity/${entityType}/${entityId}`;
        const data = await api.get<EntityRow>(url);
        if (cancelled) return;
        setEntity(data);
        setErr(null);
        setLastUpdated(new Date());
      } catch (e) {
        if (cancelled) return;
        setErr(e instanceof ApiError ? `HTTP ${e.status}` : "Load failed.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [entityType, entityId]);

  if (loading) {
    return (
      <aside className="jsp-card p-3 h-full overflow-y-auto">
        <h3 className="text-xs uppercase tracking-wider text-corp-muted">
          {LABEL_FOR[entityType]}
        </h3>
        <p className="text-xs text-corp-muted mt-3">Loading…</p>
      </aside>
    );
  }

  if (err || !entity) {
    return (
      <aside className="jsp-card p-3 h-full overflow-y-auto">
        <h3 className="text-xs uppercase tracking-wider text-corp-muted">
          {LABEL_FOR[entityType]}
        </h3>
        <p className="text-xs text-corp-danger mt-3">
          {err ?? "Entity not found"}
        </p>
      </aside>
    );
  }

  // Partition fields: filled vs empty. Filled rendered first so the
  // user sees what's there; empty rendered with a muted dash so the
  // user sees what's still being asked about.
  const entries = Object.entries(entity).filter(
    ([k]) => !HIDDEN_KEYS.has(k),
  );
  const filled: [string, unknown][] = [];
  const empty: [string, unknown][] = [];
  for (const [k, v] of entries) {
    if (isEmpty(v)) empty.push([k, v]);
    else filled.push([k, v]);
  }

  return (
    <aside className="jsp-card p-3 h-full overflow-y-auto text-sm">
      <div className="flex items-baseline justify-between gap-2 mb-2 sticky top-0 bg-corp-surface pb-2 border-b border-corp-border">
        <h3 className="text-xs uppercase tracking-wider text-corp-muted">
          {LABEL_FOR[entityType]} · live
        </h3>
        {lastUpdated ? (
          <span
            className="text-[10px] text-corp-muted"
            title="Updates every 6 seconds so you can watch the Companion's edits land."
          >
            {lastUpdated.toLocaleTimeString()}
          </span>
        ) : null}
      </div>

      <dl className="space-y-2.5">
        {filled.map(([k, v]) => (
          <EntityField key={k} k={k} v={v} />
        ))}
        {empty.length > 0 ? (
          <div className="pt-2 mt-2 border-t border-corp-border">
            <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1.5">
              Still empty
            </div>
            <div className="space-y-1.5">
              {empty.map(([k]) => (
                <div key={k} className="flex items-baseline gap-2">
                  <span className="text-[11px] text-corp-muted">{k}</span>
                  <span className="text-[11px] text-corp-muted italic">—</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </dl>
    </aside>
  );
}

function isEmpty(v: unknown): boolean {
  if (v == null) return true;
  if (typeof v === "string") return v.trim() === "";
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v as object).length === 0;
  return false;
}

function EntityField({ k, v }: { k: string; v: unknown }) {
  let display: string;
  if (typeof v === "string") display = v;
  else if (typeof v === "number" || typeof v === "boolean") display = String(v);
  else display = JSON.stringify(v);

  // Long fields (summary, description, highlights JSON) get rendered
  // as a multiline block; everything else stays inline.
  const isLong = display.length > 60 || display.includes("\n");
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-corp-muted">
        {k}
      </dt>
      {isLong ? (
        <dd className="text-[12px] whitespace-pre-wrap text-corp-text mt-0.5">
          {display}
        </dd>
      ) : (
        <dd className="text-[12px] text-corp-text">{display}</dd>
      )}
    </div>
  );
}
