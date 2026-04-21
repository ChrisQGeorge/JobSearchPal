"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Skill } from "@/lib/types";

export type LinkedSkill = {
  skill_id: number;
  name: string;
  category?: string | null;
  proficiency?: string | null;
  usage_notes?: string | null;
};

// Mode: "link" manages a list of LinkedSkill via API endpoints (for Work,
// Course, etc.). Caller provides the endpoint base.
export type SkillMultiSelectProps = {
  // API base like "/api/v1/history/work/123/skills" or
  // "/api/v1/history/courses/45/skills". Leave undefined for "unlinked" mode
  // (e.g., when parent entity hasn't been persisted yet).
  endpoint?: string;
  // Externally-controlled linked skills. Optional — the component can fetch
  // itself from `endpoint` if not provided.
  linked?: LinkedSkill[];
  onChange?: (next: LinkedSkill[]) => void;
  placeholder?: string;
  // Read-only: show the list of linked skills as chips but hide the search
  // input and remove-× buttons. Used in the default view of a parent entity.
  readOnly?: boolean;
  // Label to show when there are no linked skills in readOnly mode. Defaults
  // to a muted dash so the section reads as "empty" but isn't distracting.
  emptyLabel?: string;
};

export function SkillMultiSelect({
  endpoint,
  linked: linkedProp,
  onChange,
  placeholder = "Search skills or type to create...",
  readOnly = false,
  emptyLabel = "—",
}: SkillMultiSelectProps) {
  const [linked, setLinked] = useState<LinkedSkill[]>(linkedProp ?? []);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Skill[]>([]);
  const [highlight, setHighlight] = useState(0);
  const [busy, setBusy] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Fetch current linked skills when endpoint is provided.
  const refreshLinked = useCallback(async () => {
    if (!endpoint) return;
    const ls = await api.get<LinkedSkill[]>(endpoint);
    setLinked(ls);
    onChange?.(ls);
  }, [endpoint, onChange]);

  useEffect(() => {
    if (linkedProp !== undefined) {
      setLinked(linkedProp);
    } else if (endpoint) {
      refreshLinked();
    }
  }, [linkedProp, endpoint, refreshLinked]);

  // Search the user's skill catalog.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const q = query.trim();
    api
      .get<Skill[]>("/api/v1/history/skills")
      .then((all) => {
        if (cancelled) return;
        const linkedIds = new Set(linked.map((l) => l.skill_id));
        const filtered = all
          .filter((s) => !linkedIds.has(s.id))
          .filter((s) =>
            q ? s.name.toLowerCase().includes(q.toLowerCase()) : true,
          )
          .slice(0, 15);
        setOptions(filtered);
        setHighlight(0);
      })
      .catch(() => setOptions([]));
    return () => {
      cancelled = true;
    };
  }, [open, query, linked]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function linkExisting(skill: Skill) {
    if (!endpoint) {
      // Unlinked mode: update state only — caller will persist later.
      const next = [
        ...linked,
        {
          skill_id: skill.id,
          name: skill.name,
          category: skill.category,
          proficiency: skill.proficiency,
          usage_notes: null,
        },
      ];
      setLinked(next);
      onChange?.(next);
      setQuery("");
      return;
    }
    setBusy(true);
    try {
      await api.post<LinkedSkill>(endpoint, { skill_id: skill.id });
      await refreshLinked();
      setQuery("");
    } finally {
      setBusy(false);
    }
  }

  async function createAndLink() {
    const name = query.trim();
    if (!name) return;
    setBusy(true);
    try {
      const created = await api.post<Skill>("/api/v1/history/skills", { name });
      await linkExisting(created);
    } finally {
      setBusy(false);
    }
  }

  async function unlink(skillId: number) {
    if (!endpoint) {
      const next = linked.filter((l) => l.skill_id !== skillId);
      setLinked(next);
      onChange?.(next);
      return;
    }
    setBusy(true);
    try {
      await api.delete(`${endpoint}/${skillId}`);
      await refreshLinked();
    } finally {
      setBusy(false);
    }
  }

  const trimmed = query.trim();
  const exact = options.find(
    (s) => s.name.toLowerCase() === trimmed.toLowerCase(),
  );
  const showCreate = trimmed.length > 0 && !exact;

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    const max = options.length + (showCreate ? 1 : 0) - 1;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, Math.max(max, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (highlight < options.length) linkExisting(options[highlight]);
      else if (showCreate) createAndLink();
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  if (readOnly) {
    if (linked.length === 0) {
      return <div className="text-xs text-corp-muted">{emptyLabel}</div>;
    }
    return (
      <div className="flex flex-wrap gap-1">
        {linked.map((l) => (
          <span
            key={l.skill_id}
            className="inline-flex items-center gap-1 bg-corp-surface2 border border-corp-border rounded px-2 py-0.5 text-xs"
          >
            {l.name}
            {l.proficiency ? (
              <span className="text-corp-muted text-[10px]">· {l.proficiency}</span>
            ) : null}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="relative" ref={wrapRef}>
      <div className="jsp-input flex flex-wrap gap-1 items-center min-h-[2.5rem]">
        {linked.map((l) => (
          <span
            key={l.skill_id}
            className="inline-flex items-center gap-1 bg-corp-surface2 border border-corp-border rounded px-2 py-0.5 text-xs"
          >
            {l.name}
            {l.proficiency ? (
              <span className="text-corp-muted text-[10px]">· {l.proficiency}</span>
            ) : null}
            <button
              type="button"
              className="text-corp-muted hover:text-corp-danger ml-1"
              onClick={() => unlink(l.skill_id)}
              disabled={busy}
              aria-label={`Remove ${l.name}`}
            >
              ×
            </button>
          </span>
        ))}
        <input
          className="flex-1 min-w-[10rem] bg-transparent outline-none text-sm"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={linked.length === 0 ? placeholder : "Add another..."}
          disabled={busy}
        />
      </div>

      {open ? (
        <div className="absolute z-20 mt-1 left-0 right-0 jsp-card shadow-lg max-h-72 overflow-y-auto">
          {options.length === 0 && !showCreate ? (
            <div className="px-3 py-2 text-xs text-corp-muted">
              Type to search or create a new skill.
            </div>
          ) : null}
          {options.map((s, i) => (
            <button
              type="button"
              key={s.id}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => linkExisting(s)}
              className={`w-full text-left px-3 py-2 text-sm flex justify-between items-baseline ${
                i === highlight ? "bg-corp-surface2" : "hover:bg-corp-surface2"
              }`}
            >
              <span>{s.name}</span>
              <span className="text-[10px] uppercase tracking-wider text-corp-muted">
                {s.category}
                {s.proficiency ? ` · ${s.proficiency}` : ""}
              </span>
            </button>
          ))}
          {showCreate ? (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={createAndLink}
              className={`w-full text-left px-3 py-2 text-sm border-t border-corp-border ${
                highlight === options.length
                  ? "bg-corp-surface2"
                  : "hover:bg-corp-surface2"
              }`}
            >
              Create <span className="text-corp-accent">“{trimmed}”</span>
              <span className="text-[10px] uppercase tracking-wider text-corp-muted ml-2">
                new skill
              </span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
