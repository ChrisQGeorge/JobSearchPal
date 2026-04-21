"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  RelatedItemsPanel,
  type EntityType,
} from "@/components/RelatedItemsPanel";

// ---------------------------------------------------------------------------
// FieldDef — lightweight declarative form-field spec used by GenericEntityPanel.
// Not a full form framework — covers the 80% of flat-entity fields we need.
// ---------------------------------------------------------------------------

export type FieldDef<T> =
  | {
      key: keyof T;
      label: string;
      kind: "text" | "date" | "url" | "textarea" | "number";
      required?: boolean;
      placeholder?: string;
      fullWidth?: boolean;
    }
  | {
      key: keyof T;
      label: string;
      kind: "select";
      options: string[];
      required?: boolean;
      fullWidth?: boolean;
    }
  | {
      key: keyof T;
      label: string;
      kind: "csv"; // stores as array in the object; renders as comma-separated
      required?: boolean;
      placeholder?: string;
      fullWidth?: boolean;
    };

type GenericEntity = { id: number; [key: string]: unknown };

function toInputValue(v: unknown): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

function fromInputValue(field: FieldDef<GenericEntity>, raw: string): unknown {
  if (field.kind === "number") return raw === "" ? null : Number(raw);
  if (field.kind === "date") return raw || null;
  if (field.kind === "csv")
    return raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  return raw || null;
}

// ---------------------------------------------------------------------------
// GenericEntityPanel — list/create/edit/delete for a flat user-owned entity.
// Each item's detail view can also render a RelatedItemsPanel below its form.
// ---------------------------------------------------------------------------

type Props<T extends GenericEntity> = {
  endpoint: string; // e.g. "/api/v1/history/certifications"
  title: string;
  entityType: EntityType; // for RelatedItemsPanel
  fields: FieldDef<T>[];
  labelOf: (x: T) => string;
  subtitleOf?: (x: T) => string | null | undefined;
  emptyHint?: string;
};

export function GenericEntityPanel<T extends GenericEntity>({
  endpoint,
  title,
  entityType,
  fields,
  labelOf,
  subtitleOf,
  emptyHint,
}: Props<T>) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<T | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setItems(await api.get<T[]>(endpoint));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint]);

  async function save(data: Partial<T>, id?: number) {
    if (id) {
      await api.put(`${endpoint}/${id}`, data);
    } else {
      await api.post(endpoint, data);
    }
    setCreating(false);
    setEditing(null);
    await refresh();
  }

  async function remove(id: number) {
    if (!confirm("Delete this entry?")) return;
    await api.delete(`${endpoint}/${id}`);
    await refresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <h2 className="text-sm uppercase tracking-wider text-corp-muted">
          {title}
        </h2>
        {!creating && !editing ? (
          <button className="jsp-btn-primary" onClick={() => setCreating(true)}>
            + Add
          </button>
        ) : null}
      </div>

      {creating ? (
        <div className="jsp-card p-4">
          <EntityForm<T>
            fields={fields}
            onCancel={() => setCreating(false)}
            onSubmit={(data) => save(data)}
          />
        </div>
      ) : null}

      {loading ? (
        <p className="text-corp-muted text-sm">Loading...</p>
      ) : items.length === 0 && !creating ? (
        <div className="jsp-card p-5 text-corp-muted text-sm">
          {emptyHint ?? "No entries yet."}
        </div>
      ) : (
        <ul className="jsp-card divide-y divide-corp-border overflow-hidden">
          {items.map((it) => {
            const isEditing = editing?.id === it.id;
            if (isEditing) {
              return (
                <li key={it.id} className="p-4 space-y-4 bg-corp-surface2">
                  <EntityForm<T>
                    fields={fields}
                    initial={it}
                    onCancel={() => setEditing(null)}
                    onSubmit={(data) => save(data, it.id)}
                  />
                  <RelatedItemsPanel
                    fromType={entityType}
                    fromId={it.id}
                    title="Related items"
                  />
                </li>
              );
            }
            const subtitle = subtitleOf ? subtitleOf(it) : null;
            return (
              <li
                key={it.id}
                className="flex items-center gap-3 py-1.5 px-3 hover:bg-corp-surface2"
              >
                <div className="min-w-0 flex-1 flex items-baseline gap-2">
                  <span className="text-sm truncate">{labelOf(it)}</span>
                  {subtitle ? (
                    <span className="text-xs text-corp-muted truncate">
                      · {subtitle}
                    </span>
                  ) : null}
                </div>
                <div className="min-w-0 max-w-[40%]">
                  <RelatedItemsPanel
                    fromType={entityType}
                    fromId={it.id}
                    readOnly
                  />
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    className="jsp-btn-ghost text-xs"
                    onClick={() => setEditing(it)}
                  >
                    Edit
                  </button>
                  <button
                    className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                    onClick={() => remove(it.id)}
                  >
                    Delete
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function EntityForm<T extends GenericEntity>({
  fields,
  initial,
  onCancel,
  onSubmit,
}: {
  fields: FieldDef<T>[];
  initial?: T;
  onCancel: () => void;
  onSubmit: (data: Partial<T>) => Promise<void> | void;
}) {
  const [state, setState] = useState<Record<string, unknown>>(
    initial ? { ...initial } : {},
  );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    // Prune internal keys.
    const payload = { ...state };
    delete payload.id;
    delete payload.created_at;
    delete payload.updated_at;
    await onSubmit(payload as Partial<T>);
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        {fields.map((f) => {
          const fullWidth = "fullWidth" in f && f.fullWidth;
          const k = f.key as string;
          const wrapClass = fullWidth ? "col-span-2" : "";
          return (
            <div key={k} className={wrapClass}>
              <label className="jsp-label">
                {f.label}
                {f.required ? " *" : ""}
              </label>
              {f.kind === "textarea" ? (
                <textarea
                  className="jsp-input min-h-[80px]"
                  required={f.required}
                  value={toInputValue(state[k])}
                  placeholder={"placeholder" in f ? f.placeholder : undefined}
                  onChange={(e) =>
                    setState({ ...state, [k]: fromInputValue(f as FieldDef<GenericEntity>, e.target.value) })
                  }
                />
              ) : f.kind === "select" ? (
                <select
                  className="jsp-input"
                  value={toInputValue(state[k])}
                  onChange={(e) =>
                    setState({ ...state, [k]: e.target.value || null })
                  }
                >
                  <option value="">—</option>
                  {f.options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="jsp-input"
                  type={
                    f.kind === "date"
                      ? "date"
                      : f.kind === "number"
                        ? "number"
                        : f.kind === "url"
                          ? "url"
                          : "text"
                  }
                  required={f.required}
                  value={toInputValue(state[k])}
                  placeholder={"placeholder" in f ? f.placeholder : undefined}
                  onChange={(e) =>
                    setState({ ...state, [k]: fromInputValue(f as FieldDef<GenericEntity>, e.target.value) })
                  }
                />
              )}
            </div>
          );
        })}
      </div>
      <div className="flex justify-end gap-2">
        <button type="button" className="jsp-btn-ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="jsp-btn-primary">
          Save
        </button>
      </div>
    </form>
  );
}
