"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { OrganizationSummary, OrganizationType } from "@/lib/types";

type Props = {
  value: number | null | undefined;
  onChange: (orgId: number | null, org?: OrganizationSummary) => void;
  // Bias new-on-create selections toward a specific type (company for work,
  // university for education, etc.). User can override later on the Orgs page.
  defaultTypeOnCreate?: OrganizationType;
  placeholder?: string;
  required?: boolean;
};

// Debounce helper — keeps typeahead requests from firing on every keystroke.
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function OrganizationCombobox({
  value,
  onChange,
  defaultTypeOnCreate = "company",
  placeholder = "Type to search or create...",
  required,
}: Props) {
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("");
  const [options, setOptions] = useState<OrganizationSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debouncedQuery = useDebounced(query, 180);

  // Resolve the selected org's name when `value` is set externally (edit form).
  useEffect(() => {
    let cancelled = false;
    if (value == null) {
      setLabel("");
      return;
    }
    api
      .get<OrganizationSummary>(`/api/v1/organizations/${value}`)
      .then((o) => {
        if (!cancelled) setLabel(o.name);
      })
      .catch(() => {
        if (!cancelled) setLabel("");
      });
    return () => {
      cancelled = true;
    };
  }, [value]);

  // Typeahead fetch.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const params = new URLSearchParams();
    if (debouncedQuery.trim()) params.set("q", debouncedQuery.trim());
    params.set("limit", "10");
    api
      .get<OrganizationSummary[]>(`/api/v1/organizations?${params.toString()}`)
      .then((rs) => {
        if (!cancelled) {
          setOptions(rs);
          setHighlight(0);
        }
      })
      .catch(() => {
        if (!cancelled) setOptions([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, open]);

  // Click-outside closes the dropdown.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const trimmed = query.trim();
  const exactMatch = useMemo(
    () => options.find((o) => o.name.toLowerCase() === trimmed.toLowerCase()),
    [options, trimmed],
  );
  const showCreate = trimmed.length > 0 && !exactMatch;

  async function selectExisting(o: OrganizationSummary) {
    setLabel(o.name);
    setQuery("");
    setOpen(false);
    onChange(o.id, o);
  }

  async function createNew() {
    if (!trimmed) return;
    const created = await api.post<OrganizationSummary>("/api/v1/organizations", {
      name: trimmed,
      type: defaultTypeOnCreate,
    });
    await selectExisting(created);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const max = options.length + (showCreate ? 1 : 0) - 1;
      setHighlight((h) => Math.min(h + 1, Math.max(max, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (highlight < options.length) {
        selectExisting(options[highlight]);
      } else if (showCreate) {
        createNew();
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  function clearSelection(e: React.MouseEvent) {
    e.stopPropagation();
    setLabel("");
    onChange(null);
  }

  return (
    <div className="relative" ref={wrapperRef}>
      <div
        className="jsp-input flex items-center gap-2 cursor-text"
        onClick={() => {
          setOpen(true);
          inputRef.current?.focus();
        }}
      >
        {label && !open ? (
          <span className="flex items-center gap-2 text-corp-text">
            <span>{label}</span>
            <button
              type="button"
              onClick={clearSelection}
              className="text-corp-muted hover:text-corp-danger text-xs"
              aria-label="Clear organization"
            >
              ×
            </button>
          </span>
        ) : (
          <input
            ref={inputRef}
            className="bg-transparent outline-none flex-1 min-w-0"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            placeholder={label || placeholder}
            required={required && !label}
          />
        )}
      </div>

      {open ? (
        <div className="absolute z-20 mt-1 left-0 right-0 jsp-card shadow-lg max-h-72 overflow-y-auto">
          {loading ? (
            <div className="px-3 py-2 text-xs text-corp-muted">Searching...</div>
          ) : options.length === 0 && !showCreate ? (
            <div className="px-3 py-2 text-xs text-corp-muted">
              Type to search. Press Enter to create.
            </div>
          ) : null}
          {options.map((o, i) => (
            <button
              type="button"
              key={o.id}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => selectExisting(o)}
              className={`w-full text-left px-3 py-2 text-sm flex items-baseline justify-between gap-3 ${
                i === highlight ? "bg-corp-surface2" : "hover:bg-corp-surface2"
              }`}
            >
              <span>{o.name}</span>
              <span className="text-[10px] uppercase tracking-wider text-corp-muted">
                {o.type}
              </span>
            </button>
          ))}
          {showCreate ? (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={createNew}
              className={`w-full text-left px-3 py-2 text-sm border-t border-corp-border flex items-baseline justify-between gap-3 ${
                highlight === options.length
                  ? "bg-corp-surface2"
                  : "hover:bg-corp-surface2"
              }`}
            >
              <span>
                Create <span className="text-corp-accent">“{trimmed}”</span>
              </span>
              <span className="text-[10px] uppercase tracking-wider text-corp-muted">
                {defaultTypeOnCreate}
              </span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
