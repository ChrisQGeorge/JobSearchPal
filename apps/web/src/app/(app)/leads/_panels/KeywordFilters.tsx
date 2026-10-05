"use client";

// Saved keyword filters for the leads inbox. A filter is a NAMED group
// of conditions; each condition checks one field (job title, company,
// location, description) for any of its keywords (whole word, any
// case). Conditions combine with ALL (default — e.g. title has "AI"
// AND company is Anthropic / OpenAI) or ANY. Each filter is Off / Show
// only matches / Hide matches. Filters are saved server-side as you
// edit and applied to paging and "select all matching".

import { useState } from "react";

export type FilterField = "title" | "organization_name" | "location" | "description_md";
export type FilterCondition = { field: FilterField; keywords: string[] };
export type KeywordFilter = {
  id?: string;
  name: string;
  mode: "off" | "include" | "exclude";
  match: "all" | "any";
  // Newly imported leads that match are stored already dismissed.
  auto_dismiss?: boolean;
  conditions: FilterCondition[];
};

const FIELD_LABELS: Record<FilterField, string> = {
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

function withKeywords(c: FilterCondition, raw: string): FilterCondition {
  const have = new Set(c.keywords.map((k) => k.toLowerCase()));
  const add = splitKeywords(raw).filter((k) => !have.has(k.toLowerCase()));
  return add.length ? { ...c, keywords: [...c.keywords, ...add] } : c;
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
  // Draft keyword text per "filterIndex:conditionIndex".
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  function patch(i: number, p: Partial<KeywordFilter>) {
    onChange(filters.map((f, j) => (j === i ? { ...f, ...p } : f)));
  }
  function patchCond(i: number, ci: number, c: FilterCondition) {
    patch(i, { conditions: filters[i].conditions.map((x, j) => (j === ci ? c : x)) });
  }
  function commitDraft(i: number, ci: number) {
    const key = `${i}:${ci}`;
    const raw = drafts[key] ?? "";
    if (!raw.trim()) return;
    patchCond(i, ci, withKeywords(filters[i].conditions[ci], raw));
    setDrafts((d) => ({ ...d, [key]: "" }));
  }

  const active = filters.filter(
    (f) => f.mode !== "off" && f.conditions.some((c) => c.keywords.length),
  ).length;
  const search = searchText.trim();

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
              {
                name: "",
                mode: "include",
                match: "all",
                auto_dismiss: false,
                conditions: [{ field: "title", keywords: [] }],
              },
            ])
          }
        >
          + New filter
        </button>
        {search && filters.length > 0 ? (
          <select
            className="jsp-input text-xs py-0.5 w-auto"
            value=""
            onChange={(e) => {
              const [i, ci] = e.target.value.split(":").map(Number);
              if (Number.isNaN(i) || Number.isNaN(ci)) return;
              patchCond(i, ci, withKeywords(filters[i].conditions[ci], search));
            }}
            title="Add the current search text as a keyword"
          >
            <option value="">Save “{search.slice(0, 30)}” to…</option>
            {filters.map((f, i) =>
              f.conditions.map((c, ci) => (
                <option key={`${f.id ?? i}-${ci}`} value={`${i}:${ci}`}>
                  {f.name || "Untitled filter"} › {FIELD_LABELS[c.field]}
                </option>
              )),
            )}
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

      {filters.map((f, i) => {
        const key = f.id ?? `new-${i}`;
        const isCollapsed = !!collapsed[key];
        const kwTotal = f.conditions.reduce((n, c) => n + c.keywords.length, 0);
        return (
          <div
            key={key}
            className={`rounded border p-2 space-y-2 ${
              f.mode === "off" ? "border-corp-border" : "border-corp-accent/50 bg-corp-accent/5"
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="text-corp-muted text-xs w-4"
                onClick={() => setCollapsed((c) => ({ ...c, [key]: !isCollapsed }))}
                aria-label={isCollapsed ? "Expand filter" : "Collapse filter"}
              >
                {isCollapsed ? "▸" : "▾"}
              </button>
              <input
                className="jsp-input text-sm font-medium py-0.5 flex-1 min-w-[10rem] max-w-xs"
                value={f.name}
                placeholder="Name this filter (e.g. Too senior)"
                onChange={(e) => patch(i, { name: e.target.value })}
                aria-label="Filter name"
              />
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
              <label
                className={`text-[11px] flex items-center gap-1 ${
                  f.auto_dismiss ? "text-corp-danger" : "text-corp-muted"
                }`}
                title="When new leads are imported, ones matching this filter are saved straight to Dismissed — whatever this filter's Off / Show only / Hide setting. Leads already in the inbox aren't touched (use Show only → select all → Dismiss for those)."
              >
                <input
                  type="checkbox"
                  className="accent-corp-accent"
                  checked={!!f.auto_dismiss}
                  onChange={(e) => patch(i, { auto_dismiss: e.target.checked })}
                />
                Auto-dismiss new matches
              </label>
              {isCollapsed ? (
                <span className="text-[11px] text-corp-muted">
                  {f.conditions.length} field{f.conditions.length === 1 ? "" : "s"} · {kwTotal} keyword
                  {kwTotal === 1 ? "" : "s"}
                </span>
              ) : null}
              <button
                type="button"
                className="text-corp-muted hover:text-corp-danger text-xs ml-auto"
                onClick={() => {
                  if (kwTotal === 0 || window.confirm(`Delete the filter "${f.name || "Untitled filter"}"?`))
                    onChange(filters.filter((_, j) => j !== i));
                }}
                title="Delete filter"
              >
                ✕
              </button>
            </div>

            {!isCollapsed ? (
              <>
                {f.conditions.map((c, ci) => {
                  const dkey = `${i}:${ci}`;
                  return (
                    <div key={ci} className="pl-6 space-y-1">
                      {ci > 0 ? (
                        <div className="text-[10px] uppercase tracking-wider text-corp-muted">
                          {f.match === "all" ? "and" : "or"}
                        </div>
                      ) : null}
                      <div className="flex flex-wrap items-center gap-1">
                        <select
                          className="jsp-input text-xs py-0.5 w-auto"
                          value={c.field}
                          onChange={(e) =>
                            patchCond(i, ci, { ...c, field: e.target.value as FilterField })
                          }
                          title="Field these keywords are matched against"
                        >
                          {(Object.keys(FIELD_LABELS) as FilterField[]).map((k) => (
                            <option key={k} value={k}>
                              {FIELD_LABELS[k]}
                            </option>
                          ))}
                        </select>
                        <span className="text-[11px] text-corp-muted">contains any of</span>
                        {c.keywords.map((k) => (
                          <span
                            key={k}
                            className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-corp-surface2 border border-corp-border"
                          >
                            {k}
                            <button
                              type="button"
                              className="text-corp-muted hover:text-corp-danger"
                              onClick={() =>
                                patchCond(i, ci, { ...c, keywords: c.keywords.filter((x) => x !== k) })
                              }
                              aria-label={`Remove ${k}`}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                        <input
                          className="jsp-input text-xs py-0.5 w-44"
                          placeholder={c.keywords.length ? "add keyword…" : "keyword, Enter (or paste a list)"}
                          value={drafts[dkey] ?? ""}
                          onChange={(e) => setDrafts((d) => ({ ...d, [dkey]: e.target.value }))}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === ",") {
                              e.preventDefault();
                              commitDraft(i, ci);
                            }
                          }}
                          onBlur={() => commitDraft(i, ci)}
                        />
                        {f.conditions.length > 1 ? (
                          <button
                            type="button"
                            className="text-corp-muted hover:text-corp-danger text-[11px] ml-1"
                            onClick={() =>
                              patch(i, { conditions: f.conditions.filter((_, j) => j !== ci) })
                            }
                            title="Remove this field condition"
                          >
                            remove field
                          </button>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
                <div className="pl-6 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="jsp-btn-ghost text-[11px] py-0.5"
                    onClick={() =>
                      patch(i, {
                        conditions: [...f.conditions, { field: "organization_name", keywords: [] }],
                      })
                    }
                    disabled={f.conditions.length >= 10}
                  >
                    + Add field
                  </button>
                  {f.conditions.length > 1 ? (
                    <label className="text-[11px] text-corp-muted flex items-center gap-1">
                      Match
                      <select
                        className="jsp-input text-[11px] py-0 w-auto"
                        value={f.match}
                        onChange={(e) => patch(i, { match: e.target.value as KeywordFilter["match"] })}
                      >
                        <option value="all">all fields (and)</option>
                        <option value="any">any field (or)</option>
                      </select>
                    </label>
                  ) : null}
                </div>
              </>
            ) : null}
          </div>
        );
      })}
      {filters.length > 0 ? (
        <p className="text-[10px] text-corp-muted">
          Keywords match whole words, any case (“Sr” matches “Sr.” and “SR” but not “Srinivas”).
          Each condition only looks at its own field. Show-only filters must all match; any Hide
          filter removes a lead.
        </p>
      ) : null}
    </div>
  );
}
