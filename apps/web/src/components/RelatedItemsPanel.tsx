"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export type EntityType =
  | "work"
  | "education"
  | "course"
  | "certification"
  | "project"
  | "publication"
  | "presentation"
  | "achievement"
  | "volunteer"
  | "language"
  | "contact"
  | "custom"
  | "tracked_job"
  | "skill";

export type EntityLink = {
  id: number;
  from_entity_type: EntityType;
  from_entity_id: number;
  to_entity_type: EntityType;
  to_entity_id: number;
  relation: string;
  note: string | null;
  to_label: string | null;
};

// Endpoint per type that lists items the user owns. Matches router paths.
const LIST_ENDPOINTS: Record<EntityType, string> = {
  work: "/api/v1/history/work",
  education: "/api/v1/history/education",
  course: "/api/v1/history/courses",
  certification: "/api/v1/history/certifications",
  project: "/api/v1/history/projects",
  publication: "/api/v1/history/publications",
  presentation: "/api/v1/history/presentations",
  achievement: "/api/v1/history/achievements",
  volunteer: "/api/v1/history/volunteer",
  language: "/api/v1/history/languages",
  contact: "/api/v1/history/contacts",
  custom: "/api/v1/history/custom-events",
  tracked_job: "/api/v1/jobs",
  skill: "/api/v1/history/skills",
};

// How to pull a label from each type's list entries.
const LABEL_KEY: Record<EntityType, string> = {
  work: "title",
  education: "organization_name", // falls back to degree below
  course: "name",
  certification: "name",
  project: "name",
  publication: "title",
  presentation: "title",
  achievement: "title",
  volunteer: "organization",
  language: "name",
  contact: "name",
  custom: "title",
  tracked_job: "title",
  skill: "name",
};

// Human labels for type pills.
const TYPE_LABELS: Record<EntityType, string> = {
  work: "Work",
  education: "Education",
  course: "Course",
  certification: "Certification",
  project: "Project",
  publication: "Publication",
  presentation: "Presentation",
  achievement: "Achievement",
  volunteer: "Volunteer",
  language: "Language",
  contact: "Contact",
  custom: "Custom Event",
  tracked_job: "Tracked Job",
  skill: "Skill",
};

type Props = {
  fromType: EntityType;
  fromId: number;
  // Which entity types to offer as link targets. Defaults to "everything except from itself".
  allowedToTypes?: EntityType[];
  title?: string;
  // Read-only: show the list of linked items but hide the +Link button and
  // per-row remove-× buttons. Used in the default view of a parent entity.
  readOnly?: boolean;
};

export function RelatedItemsPanel({
  fromType,
  fromId,
  allowedToTypes,
  title = "Related items",
  readOnly = false,
}: Props) {
  const [links, setLinks] = useState<EntityLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const ls = await api.get<EntityLink[]>(
        `/api/v1/history/links?from_entity_type=${fromType}&from_entity_id=${fromId}`,
      );
      setLinks(ls);
    } finally {
      setLoading(false);
    }
  }, [fromType, fromId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function remove(id: number) {
    await api.delete(`/api/v1/history/links/${id}`);
    await refresh();
  }

  const defaultAllowed: EntityType[] =
    allowedToTypes ??
    (Object.keys(LIST_ENDPOINTS) as EntityType[]).filter((t) => t !== fromType);

  // Read-only mode: compact inline listing, no header controls or row buttons.
  // If nothing is linked we render nothing (caller can decide to show a
  // placeholder in its own layout).
  if (readOnly) {
    if (loading) return null;
    if (links.length === 0) return null;
    return (
      <ul className="flex flex-wrap gap-1.5">
        {links.map((l) => (
          <li
            key={l.id}
            className="inline-flex items-baseline gap-1 bg-corp-surface2 border border-corp-border rounded px-2 py-0.5 text-xs"
            title={l.note ?? undefined}
          >
            <span className="text-[9px] uppercase tracking-wider text-corp-muted">
              {TYPE_LABELS[l.to_entity_type]}
            </span>
            <span>{l.to_label ?? `#${l.to_entity_id}`}</span>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section className="jsp-card p-4">
      <header className="flex justify-between items-center mb-3">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">
          {title}
        </h3>
        {!adding ? (
          <button
            type="button"
            className="jsp-btn-ghost text-xs"
            onClick={() => setAdding(true)}
          >
            + Link
          </button>
        ) : null}
      </header>

      {loading ? (
        <p className="text-xs text-corp-muted">Loading...</p>
      ) : links.length === 0 && !adding ? (
        <p className="text-xs text-corp-muted">Nothing linked yet.</p>
      ) : (
        <ul className="space-y-1">
          {links.map((l) => (
            <li
              key={l.id}
              className="flex items-center justify-between gap-2 text-sm py-1"
            >
              <span className="flex items-center gap-2 min-w-0">
                <span className="text-[10px] uppercase tracking-wider text-corp-muted shrink-0">
                  {TYPE_LABELS[l.to_entity_type]}
                </span>
                <span className="truncate">{l.to_label ?? `#${l.to_entity_id}`}</span>
                {l.note ? (
                  <span className="text-corp-muted italic">— {l.note}</span>
                ) : null}
              </span>
              <button
                type="button"
                className="text-corp-muted hover:text-corp-danger text-xs shrink-0"
                onClick={() => remove(l.id)}
                aria-label="Unlink"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <AddLinkRow
          fromType={fromType}
          fromId={fromId}
          allowed={defaultAllowed}
          onCancel={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            refresh();
          }}
        />
      ) : null}
    </section>
  );
}

type Option = { id: number; label: string };

function AddLinkRow({
  fromType,
  fromId,
  allowed,
  onCancel,
  onSaved,
}: {
  fromType: EntityType;
  fromId: number;
  allowed: EntityType[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [toType, setToType] = useState<EntityType>(allowed[0]);
  const [options, setOptions] = useState<Option[]>([]);
  const [toId, setToId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const loadedFor = useRef<EntityType | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setToId(null);
    loadedFor.current = toType;
    api
      .get<Record<string, unknown>[]>(LIST_ENDPOINTS[toType])
      .then((rows) => {
        if (cancelled || loadedFor.current !== toType) return;
        const key = LABEL_KEY[toType];
        const opts: Option[] = rows
          .map((r) => {
            const id = Number(r.id);
            let label = String(r[key] ?? "").trim();
            // Education falls back to degree / field if org_name is empty.
            if (!label && toType === "education") {
              const parts = [r["degree"], r["field_of_study"]].filter(Boolean);
              label = parts.join(" ").trim() || `Education #${id}`;
            }
            if (!label) label = `${TYPE_LABELS[toType]} #${id}`;
            // Exclude self-links.
            if (toType === fromType && id === fromId) return null;
            return { id, label };
          })
          .filter((x): x is Option => x !== null);
        setOptions(opts);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [toType, fromType, fromId]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!toId) return;
    setSaving(true);
    try {
      await api.post("/api/v1/history/links", {
        from_entity_type: fromType,
        from_entity_id: fromId,
        to_entity_type: toType,
        to_entity_id: toId,
        relation: "related",
        note: note.trim() || null,
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 border-t border-corp-border pt-3 space-y-2">
      <div className="flex flex-wrap gap-2 items-end">
        <div>
          <label className="jsp-label">Type</label>
          <select
            className="jsp-input"
            value={toType}
            onChange={(e) => setToType(e.target.value as EntityType)}
          >
            {allowed.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1 min-w-[14rem]">
          <label className="jsp-label">Item</label>
          <select
            className="jsp-input"
            value={toId ?? ""}
            onChange={(e) => setToId(e.target.value ? Number(e.target.value) : null)}
            disabled={loading}
          >
            <option value="">
              {loading
                ? "Loading..."
                : options.length === 0
                  ? "(none recorded yet)"
                  : "Select..."}
            </option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="jsp-label">Note (optional)</label>
        <input
          className="jsp-input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. capstone project, mentored by, drove adoption of..."
        />
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="submit"
          className="jsp-btn-primary"
          disabled={saving || !toId}
        >
          {saving ? "..." : "Link"}
        </button>
      </div>
    </form>
  );
}
