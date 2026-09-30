"use client";

// Settings → Jev Scoring: the five scoring dimensions Jev is asked on,
// fully editable — instructions, the ordered worst→best criteria levels,
// and each dimension's weight in the overall average. The candidate
// profile block and the apply yes/no judgment stay fixed by design.

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type JevDimension = {
  key: string;
  label: string;
  instructions: string;
  criteria: string[];
  weight: number;
  overridden: boolean;
  default_instructions: string;
  default_criteria: string[];
};

type JevSettings = {
  dimensions: JevDimension[];
  limits?: { min_criteria: number; max_criteria: number; max_weight: number };
};

export function JevScoringPanel() {
  const [dims, setDims] = useState<JevDimension[] | null>(null);
  const [limits, setLimits] = useState({
    min_criteria: 2,
    max_criteria: 10,
    max_weight: 5,
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<JevSettings>("/api/v1/jev/scoring-settings")
      .then((s) => {
        setDims(s.dimensions);
        if (s.limits) setLimits(s.limits);
      })
      .catch(() => setMsg("Could not load Jev scoring settings."));
  }, []);

  function patchDim(key: string, patch: Partial<JevDimension>) {
    setDims((prev) =>
      prev ? prev.map((d) => (d.key === key ? { ...d, ...patch } : d)) : prev,
    );
    setMsg(null);
  }

  async function save() {
    if (!dims) return;
    setSaving(true);
    setMsg(null);
    try {
      const overrides: Record<
        string,
        { instructions: string; criteria: string[] }
      > = {};
      const weights: Record<string, number> = {};
      for (const d of dims) {
        overrides[d.key] = {
          instructions: d.instructions.trim(),
          criteria: d.criteria.map((c) => c.trim()).filter(Boolean),
        };
        weights[d.key] = d.weight;
      }
      const out = await api.put<JevSettings>("/api/v1/jev/scoring-settings", {
        overrides,
        weights,
      });
      setDims(out.dimensions);
      setMsg("Saved. The next score run (or a bulk Rescore) uses these prompts.");
    } catch (e) {
      setMsg(
        e instanceof ApiError
          ? `Save failed (HTTP ${e.status}). Each dimension needs instructions and ${limits.min_criteria}–${limits.max_criteria} non-empty criteria.`
          : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (dims === null) {
    return (
      <div className="jsp-card p-4 text-sm text-corp-muted">
        {msg ?? "Loading Jev scoring settings…"}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="jsp-card p-4">
        <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-1">
          Jev scoring priorities
        </h3>
        <p className="text-xs text-corp-muted">
          These are the exact prompts Jev scores each job against. Edit the
          instructions and the ordered levels (worst first, best last) to
          tell it what matters to you, and use the weight to change how
          much each dimension counts in the overall score (0 removes it
          from the average; subscores still show). Changes apply to the
          next scoring run — use the tracker&apos;s Rescore bulk action to
          re-run existing jobs.
        </p>
      </div>

      {dims.map((d) => {
        const isDefault =
          d.instructions.trim() === d.default_instructions &&
          d.criteria.length === d.default_criteria.length &&
          d.criteria.every((c, i) => c.trim() === d.default_criteria[i]);
        return (
          <div key={d.key} className="jsp-card p-4 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-medium">{d.label}</h4>
              {!isDefault ? (
                <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-corp-accent/15 text-corp-accent border border-corp-accent/40">
                  customized
                </span>
              ) : null}
              <div className="ml-auto flex items-center gap-1.5">
                <label className="text-[10px] uppercase tracking-wider text-corp-muted">
                  Weight
                </label>
                <input
                  type="number"
                  className="jsp-input text-xs py-1 w-20"
                  min={0}
                  max={limits.max_weight}
                  step={0.5}
                  value={d.weight}
                  onChange={(e) =>
                    patchDim(d.key, {
                      weight: Math.max(
                        0,
                        Math.min(limits.max_weight, Number(e.target.value) || 0),
                      ),
                    })
                  }
                  disabled={saving}
                  title="How much this dimension counts in the overall score. 1 = normal, 0 = excluded from the average."
                />
                <button
                  type="button"
                  className="jsp-btn-ghost text-xs"
                  onClick={() =>
                    patchDim(d.key, {
                      instructions: d.default_instructions,
                      criteria: [...d.default_criteria],
                      weight: 1,
                    })
                  }
                  disabled={saving || (isDefault && d.weight === 1)}
                >
                  Reset
                </button>
              </div>
            </div>
            <div>
              <label className="jsp-label">Instructions</label>
              <textarea
                className="jsp-input text-xs min-h-[72px]"
                value={d.instructions}
                onChange={(e) =>
                  patchDim(d.key, { instructions: e.target.value })
                }
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <label className="jsp-label">
                Levels (worst → best; the score is Jev&apos;s
                probability-weighted position on this ladder)
              </label>
              {d.criteria.map((c, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  <span className="text-[10px] text-corp-muted w-5 pt-2 text-right shrink-0">
                    {i + 1}.
                  </span>
                  <textarea
                    className="jsp-input text-xs min-h-[40px] flex-1"
                    value={c}
                    onChange={(e) => {
                      const criteria = d.criteria.slice();
                      criteria[i] = e.target.value;
                      patchDim(d.key, { criteria });
                    }}
                    disabled={saving}
                  />
                  <button
                    type="button"
                    className="jsp-btn-ghost text-xs text-corp-danger shrink-0"
                    onClick={() =>
                      patchDim(d.key, {
                        criteria: d.criteria.filter((_, j) => j !== i),
                      })
                    }
                    disabled={saving || d.criteria.length <= limits.min_criteria}
                    title="Remove this level"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="jsp-btn-ghost text-xs"
                onClick={() =>
                  patchDim(d.key, { criteria: [...d.criteria, ""] })
                }
                disabled={saving || d.criteria.length >= limits.max_criteria}
              >
                + Add level
              </button>
            </div>
          </div>
        );
      })}

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="jsp-btn-primary"
          onClick={save}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save Jev scoring settings"}
        </button>
        {msg ? <span className="text-xs text-corp-muted">{msg}</span> : null}
      </div>
    </div>
  );
}
