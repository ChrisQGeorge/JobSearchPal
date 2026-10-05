"use client";

// Saved keyword filters for the leads inbox. Each filter checks ONE
// field with a list of keywords (whole-word, case-insensitive, any one
// matches) and is Off / Show only matches / Hide matches. Filters are
// saved server-side as you edit them and applied to paging and to
// "select all matching", so "show only Sr/Senior titles → select all →
// Dismiss" works across every lead.

import { useState } from "react";

export type KeywordFilter = {
  id?: string;
  name: string;
  field: "title" | "organization_name" | "location" | "description_md";
  mode: "off" | "include" | "exclude";
  keywords: string[];
};

const FIELD_LABELS: Record<KeywordFilter["field"], string> = {
  title: "Job title",
  organization_name: "Company",
  location: "Location",
  description_md: "Description",
};

const MODE_LABELS: Record<KeywordFilter["mode"], string> = {
  off: "Off",
  include: "Show only",
  exclude: "Hide",
};

function splitKeywords(raw: string): string[] {
  return raw
    .split(/[,;\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function KeywordFilters({
  filters,
  counts,
  onChange,
  searchText,
}: {
  filters: KeywordFilter[];
  counts: Record<string, number>;
  onChange: (next: KeywordFilter[]) => void;
  searchText: string;
}) {
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  function patch(i: number, p: Partial<KeywordFilter>) {
    onChange(filters.map((f, j) => (j === i ? { ...f, ...p } : f)));
  }
  function addKeywords(i: number, raw: string) {
    const add = splitKeywords(raw);
    if (!add.length) return;
    const have = new Set(filters[i].keywords.map((k) => k.toLowerCase()));
    patch(i, {
      keywords: [...filters[i].keywords, ...add.filter((k) => !have.has(k.toLowerCase()))],
    });
    setDrafts((d) => ({ ...d, [i]: "" }));
  }

  const active = filters.filter((f) => f.mode !== "off" && f.keywords.length).length;

  return (
    <div className="mb-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-corp-muted">
          Keyword filters{active ? ` · ${active} active` : ""}
        </span>
        <button
          type="button"
          className="jsp-btn-ghost text-xs"
          onClick={() =>
            onChange([
              ...filters,
              { name: `Filter ${filters.length + 1}`, field: "title", mode: "include", keywords: [] },
            ])
          }
        >
          + New filter
        </button>
        {searchText.trim() && filters.length > 0 ? (
          <select
            className="jsp-input text-xs py-0.5 w-auto"
            value=""
            onChange={(e) => {
              const i = Number(e.target.value);
              if (!Number.isNaN(i)) addKeywords(i, searchText);
            }}
            title="Save the current search text as a keyword in one of your filters"
          >
            <option value="">Save “{searchText.trim().slice(0, 30)}” to filter…</option>
            {filters.map((f, i) => (
              <option key={f.id ?? i} value={i}>
                {f.name} ({FIELD_LABELS[f.field]})
              </option>
            ))}
          </select>
        ) : null}
        {active > 0 ? (
          <button
            type="button"
            className="jsp-btn-ghost text-xs ml-auto"
            onClick={() => onChange(filters.map((f) => ({ ...f, mode: "off" })))}
          >
            Turn all off
          </button>
        ) : null}
      </div>

      {filters.map((f, i) => (
        <div
          key={f.id ?? `new-${i}`}
          className={`rounded border p-2 space-y-1.5 ${
            f.mode === "off" ? "border-corp-border" : "border-corp-accent/50 bg-corp-accent/5"
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="jsp-input text-xs py-0.5 w-36"
              value={f.name}
              onChange={(e) => patch(i, { name: e.target.value })}
              aria-label="Filter name"
            />
            <select
              className="jsp-input text-xs py-0.5 w-auto"
              value={f.field}
              onChange={(e) => patch(i, { field: e.target.value as KeywordFilter["field"] })}
              title="Which field the keywords are matched against"
            >
              {(Object.keys(FIELD_LABELS) as KeywordFilter["field"][]).map((k) => (
                <option key={k} value={k}>
                  {FIELD_LABELS[k]}
                </option>
              ))}
            </select>
            <div className="inline-flex rounded border border-corp-border overflow-hidden">
              {(Object.keys(MODE_LABELS) as KeywordFilter["mode"][]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => patch(i, { mode: m })}
                  className={`px-2 py-0.5 text-[11px] ${
                    f.mode === m
                      ? m === "exclude"
                        ? "bg-corp-danger/20 text-corp-danger"
                        : m === "include"
                          ? "bg-corp-accent/25 text-corp-accent"
                          : "bg-corp-surface2 text-corp-text"
                      : "text-corp-muted hover:text-corp-text"
                  }`}
                >
                  {MODE_LABELS[m]}
                </button>
              ))}
            </div>
            {f.id && counts[f.id] != null ? (
              <span className="text-[11px] text-corp-muted">
                matches {counts[f.id].toLocaleString()}
              </span>
            ) : null}
            <button
              type="button"
              className="text-corp-muted hover:text-corp-danger text-xs ml-auto"
              onClick={() => onChange(filters.filter((_, j) => j !== i))}
              title="Delete filter"
            >
              ✕
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {f.keywords.map((k) => (
              <span
                key={k}
                className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-corp-surface2 border border-corp-border"
              >
                {k}
                <button
                  type="button"
                  className="text-corp-muted hover:text-corp-danger"
                  onClick={() => patch(i, { keywords: f.keywords.filter((x) => x !== k) })}
                  aria-label={`Remove ${k}`}
                >
                  ×
                </button>
              </span>
            ))}
            <input
              className="jsp-input text-xs py-0.5 w-40"
              placeholder={f.keywords.length ? "add keyword…" : "type a keyword, Enter"}
              value={drafts[i] ?? ""}
              onChange={(e) => setDrafts((d) => ({ ...d, [i]: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addKeywords(i, drafts[i] ?? "");
                }
              }}
              onBlur={() => addKeywords(i, drafts[i] ?? "")}
            />
          </div>
        </div>
      ))}
      {filters.length > 0 ? (
        <p className="text-[10px] text-corp-muted">
          Keywords match whole words, any case (“Sr” matches “Sr.” and “SR” but not “Srinivas”).
          Each filter only looks at its own field. Show-only filters must all match; any Hide
          filter removes a lead.
        </p>
      ) : null}
    </div>
  );
}
