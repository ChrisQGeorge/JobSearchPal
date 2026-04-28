"use client";

// Cmd-K / Ctrl-K global search palette. Indexes tracked jobs,
// organizations, generated documents, and catalog skills client-side
// after a single fetch on first open. Result rows route to the matching
// detail page on Enter / click.
//
// Why client-side: the existing API endpoints are already paginated /
// filtered for their own pages, but none of them is a global search,
// and the dataset for a single user is small (tens to low thousands of
// rows max). One round-trip on first open is fine.

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  GeneratedDocument,
  Skill,
  TrackedJobSummary,
} from "@/lib/types";

type Org = { id: number; name: string };

type SearchHit = {
  kind: "job" | "org" | "doc" | "skill";
  id: number;
  label: string;
  sub: string;
  href: string;
  rank: number;
};

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [hydrated, setHydrated] = useState(false);
  const [jobs, setJobs] = useState<TrackedJobSummary[]>([]);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [docs, setDocs] = useState<GeneratedDocument[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Open / close on Cmd-K / Ctrl-K. Escape closes. Ignore the shortcut
  // when the focused element is a text input — typing K in a search
  // box should produce a K, not steal focus.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isModK =
        (e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey);
      if (isModK) {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (open && e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Hydrate the search corpus the first time the palette opens. We keep
  // it in memory thereafter; a full reload refetches.
  useEffect(() => {
    if (!open || hydrated) return;
    Promise.all([
      api
        .get<TrackedJobSummary[]>("/api/v1/jobs")
        .catch(() => [] as TrackedJobSummary[]),
      api.get<Org[]>("/api/v1/organizations").catch(() => [] as Org[]),
      api
        .get<GeneratedDocument[]>("/api/v1/documents")
        .catch(() => [] as GeneratedDocument[]),
      api.get<Skill[]>("/api/v1/history/skills").catch(() => [] as Skill[]),
    ]).then(([j, o, d, s]) => {
      setJobs(j);
      setOrgs(o);
      setDocs(d);
      setSkills(s);
      setHydrated(true);
    });
  }, [open, hydrated]);

  // Focus the input every time the palette opens (covers reopen-after-close).
  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // Defer until after the input is in the DOM.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const hits: SearchHit[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      // No query: surface a small "recent" set across kinds so the
      // palette is useful even before the user types anything.
      const recent: SearchHit[] = [];
      for (const j of jobs.slice(0, 5)) {
        recent.push({
          kind: "job",
          id: j.id,
          label: j.title,
          sub: j.organization_name ?? j.location ?? j.status,
          href: `/jobs/${j.id}`,
          rank: 0,
        });
      }
      for (const d of docs.slice(0, 3)) {
        recent.push({
          kind: "doc",
          id: d.id,
          label: d.title,
          sub: d.doc_type.replace(/_/g, " "),
          href: `/studio/${d.id}`,
          rank: 0,
        });
      }
      return recent;
    }
    function score(haystack: string): number {
      const h = haystack.toLowerCase();
      if (!h) return -1;
      if (h === q) return 100;
      if (h.startsWith(q)) return 60;
      if (h.includes(q)) return 30;
      // Fuzzy: every char in q appears in order in h.
      let i = 0;
      for (const ch of h) {
        if (ch === q[i]) i++;
        if (i === q.length) return 10;
      }
      return -1;
    }
    const out: SearchHit[] = [];
    for (const j of jobs) {
      const r = Math.max(
        score(j.title),
        score(j.organization_name ?? ""),
        score(j.location ?? ""),
      );
      if (r > 0) {
        out.push({
          kind: "job",
          id: j.id,
          label: j.title,
          sub: j.organization_name ?? j.location ?? j.status,
          href: `/jobs/${j.id}`,
          rank: r,
        });
      }
    }
    for (const o of orgs) {
      const r = score(o.name);
      if (r > 0) {
        out.push({
          kind: "org",
          id: o.id,
          label: o.name,
          sub: "Organization",
          href: `/organizations#org-${o.id}`,
          rank: r,
        });
      }
    }
    for (const d of docs) {
      const r = Math.max(score(d.title), score(d.doc_type ?? ""));
      if (r > 0) {
        out.push({
          kind: "doc",
          id: d.id,
          label: d.title,
          sub: `${d.doc_type.replace(/_/g, " ")} · v${d.version}`,
          href: `/studio/${d.id}`,
          rank: r,
        });
      }
    }
    for (const s of skills) {
      const r = Math.max(
        score(s.name),
        ...(s.aliases ?? []).map(score),
      );
      if (r > 0) {
        out.push({
          kind: "skill",
          id: s.id,
          label: s.name,
          sub: `Skill${s.category ? ` · ${s.category}` : ""}`,
          href: "/history#skills",
          rank: r,
        });
      }
    }
    out.sort((a, b) => b.rank - a.rank);
    return out.slice(0, 30);
  }, [query, jobs, orgs, docs, skills]);

  // Reset highlight whenever the result set changes (typing).
  useEffect(() => {
    setActive(0);
  }, [query]);

  function go(hit: SearchHit | undefined) {
    if (!hit) return;
    setOpen(false);
    router.push(hit.href);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(hits.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(hits[active]);
    }
  }

  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-label="Global search"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 py-[10vh]"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl jsp-card overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Search jobs, orgs, documents, skills…"
          className="w-full bg-transparent border-0 border-b border-corp-border px-4 py-3 text-sm outline-none focus:border-corp-accent"
        />
        <ul className="max-h-[50vh] overflow-y-auto" role="listbox">
          {!hydrated ? (
            <li className="px-4 py-3 text-sm text-corp-muted">Loading…</li>
          ) : hits.length === 0 ? (
            <li className="px-4 py-3 text-sm text-corp-muted">
              {query ? "No matches." : "Type to search."}
            </li>
          ) : (
            hits.map((h, i) => (
              <li
                key={`${h.kind}:${h.id}`}
                role="option"
                aria-selected={i === active}
                className={`px-4 py-2 cursor-pointer flex items-center gap-3 ${
                  i === active ? "bg-corp-accent/15" : "hover:bg-corp-surface2"
                }`}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(h)}
              >
                <span className="inline-block w-12 shrink-0 text-[10px] uppercase tracking-wider text-corp-muted">
                  {h.kind}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="text-sm truncate block">{h.label}</span>
                  <span className="text-[11px] text-corp-muted truncate block">
                    {h.sub}
                  </span>
                </span>
              </li>
            ))
          )}
        </ul>
        <div className="border-t border-corp-border px-4 py-2 text-[10px] text-corp-muted flex justify-between">
          <span>
            <kbd>↑</kbd>/<kbd>↓</kbd> navigate · <kbd>Enter</kbd> open ·{" "}
            <kbd>Esc</kbd> close
          </span>
          <span>
            <kbd>{navigatorMod()}+K</kbd>
          </span>
        </div>
      </div>
    </div>
  );
}

function navigatorMod(): string {
  if (typeof navigator === "undefined") return "Ctrl";
  return /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";
}
