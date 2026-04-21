"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Skill } from "@/lib/types";

type Props = {
  required: string[] | null | undefined;
  niceToHave: string[] | null | undefined;
  // Called after the user adds a missing skill to their catalog so the parent
  // can refresh its view if it displays the skill set.
  onSkillAdded?: (skill: Skill) => void;
};

function normalize(name: string): string {
  return name.trim().toLowerCase();
}

/**
 * Compares the JD's skill lists (required + nice-to-have) against the user's
 * catalog. Matches (normalize-equal) render as chips; misses render with a
 * one-click "+ Add" button that creates a Skill in the catalog.
 */
export function SkillsAnalysis({ required, niceToHave, onSkillAdded }: Props) {
  const [catalog, setCatalog] = useState<Skill[]>([]);
  const [busyFor, setBusyFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setCatalog(await api.get<Skill[]>("/api/v1/history/skills"));
    } catch {
      /* best-effort */
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const { matchingRequired, missingRequired, matchingNice, missingNice } = useMemo(() => {
    const catSet = new Set(catalog.map((s) => normalize(s.name)));
    const classify = (list: string[] | null | undefined) => {
      const matching: string[] = [];
      const missing: string[] = [];
      for (const raw of list ?? []) {
        const n = raw.trim();
        if (!n) continue;
        if (catSet.has(normalize(n))) matching.push(n);
        else missing.push(n);
      }
      return { matching, missing };
    };
    const req = classify(required);
    const nice = classify(niceToHave);
    return {
      matchingRequired: req.matching,
      missingRequired: req.missing,
      matchingNice: nice.matching,
      missingNice: nice.missing,
    };
  }, [required, niceToHave, catalog]);

  async function addToCatalog(name: string, category = "technical") {
    setBusyFor(name);
    setError(null);
    try {
      const created = await api.post<Skill>("/api/v1/history/skills", {
        name,
        category,
      });
      await refresh();
      onSkillAdded?.(created);
    } catch {
      setError(`Couldn't add "${name}".`);
    } finally {
      setBusyFor(null);
    }
  }

  const haveAnything =
    (required && required.length > 0) || (niceToHave && niceToHave.length > 0);
  if (!haveAnything) return null;

  return (
    <section className="jsp-card p-4 space-y-3">
      <header className="flex justify-between items-baseline">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted">
          Skills match
        </h3>
        <span className="text-xs text-corp-muted">
          {matchingRequired.length + matchingNice.length} matching ·{" "}
          {missingRequired.length + missingNice.length} missing
        </span>
      </header>

      {required && required.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Required
          </div>
          <div className="flex flex-wrap gap-1.5">
            {matchingRequired.map((s) => (
              <MatchChip key={"m-" + s} name={s} />
            ))}
            {missingRequired.map((s) => (
              <MissingChip
                key={"x-" + s}
                name={s}
                busy={busyFor === s}
                onAdd={() => addToCatalog(s, "technical")}
              />
            ))}
          </div>
        </div>
      ) : null}

      {niceToHave && niceToHave.length > 0 ? (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
            Nice to have
          </div>
          <div className="flex flex-wrap gap-1.5">
            {matchingNice.map((s) => (
              <MatchChip key={"m-" + s} name={s} />
            ))}
            {missingNice.map((s) => (
              <MissingChip
                key={"x-" + s}
                name={s}
                busy={busyFor === s}
                onAdd={() => addToCatalog(s, "technical")}
              />
            ))}
          </div>
        </div>
      ) : null}

      {error ? <div className="text-xs text-corp-danger">{error}</div> : null}
    </section>
  );
}

function MatchChip({ name }: { name: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 rounded px-2 py-0.5 text-xs"
      title="You have this skill in your catalog"
    >
      <span aria-hidden>✓</span>
      {name}
    </span>
  );
}

function MissingChip({
  name,
  busy,
  onAdd,
}: {
  name: string;
  busy: boolean;
  onAdd: () => void;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 bg-corp-accent2/15 border border-corp-accent2/40 text-corp-accent2 rounded px-2 py-0.5 text-xs"
      title={`"${name}" isn't in your Skills catalog yet`}
    >
      {name}
      <button
        type="button"
        onClick={onAdd}
        disabled={busy}
        className="ml-1 bg-corp-accent2/25 hover:bg-corp-accent2/50 text-corp-accent2 rounded px-1 text-[10px] uppercase tracking-wider"
        aria-label={`Add ${name} to my skills`}
      >
        {busy ? "..." : "+ Add"}
      </button>
    </span>
  );
}
