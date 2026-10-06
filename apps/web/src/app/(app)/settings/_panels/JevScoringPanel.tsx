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

type ApplyQuestion = {
  instructions: string;
  criteria_true: string;
  criteria_false: string;
  go_threshold: number;
  nogo_threshold: number;
  overridden?: boolean;
  defaults?: Omit<ApplyQuestion, "overridden" | "defaults">;
};

type EmailQuestion = {
  key: string;
  label: string;
  text: string;
  default: string;
  overridden: boolean;
};

type JevSettings = {
  dimensions: JevDimension[];
  apply?: ApplyQuestion;
  email_questions?: EmailQuestion[];
  unacceptable_industries?: string[];
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
  const [apply, setApply] = useState<ApplyQuestion | null>(null);
  const [blockedIndustries, setBlockedIndustries] = useState<string[]>([]);
  const [emailQs, setEmailQs] = useState<EmailQuestion[]>([]);

  useEffect(() => {
    api
      .get<JevSettings>("/api/v1/jev/scoring-settings")
      .then((s) => {
        setDims(s.dimensions);
        if (s.limits) setLimits(s.limits);
        if (s.apply) setApply(s.apply);
        setBlockedIndustries(s.unacceptable_industries ?? []);
        setEmailQs(s.email_questions ?? []);
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
        apply: apply
          ? {
              instructions: apply.instructions.trim(),
              criteria_true: apply.criteria_true.trim(),
              criteria_false: apply.criteria_false.trim(),
              go_threshold: apply.go_threshold,
              nogo_threshold: apply.nogo_threshold,
            }
          : undefined,
        email_questions: emailQs.length
          ? Object.fromEntries(emailQs.map((q) => [q.key, q.text.trim()]))
          : undefined,
      });
      setDims(out.dimensions);
      if (out.apply) setApply(out.apply);
      if (out.email_questions) setEmailQs(out.email_questions);
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

      {apply ? (
        <div className="jsp-card p-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-medium">Worth applying? (GO / MAYBE / NO-GO)</h4>
            {apply.overridden ? (
              <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-corp-accent/15 text-corp-accent border border-corp-accent/40">
                customized
              </span>
            ) : null}
            {apply.defaults ? (
              <button
                type="button"
                className="jsp-btn-ghost text-xs ml-auto"
                onClick={() => {
                  setApply({ ...apply, ...apply.defaults! });
                  setMsg(null);
                }}
                disabled={saving}
              >
                Reset
              </button>
            ) : null}
          </div>
          <p className="text-[11px] text-corp-muted">
            A separate yes/no question in the same Jev call. Its probability sets the
            recommendation: GO at or above the GO threshold, NO-GO at or below the
            NO-GO threshold, MAYBE in between. It doesn&apos;t change the fit score.
          </p>
          <div>
            <label className="jsp-label">Question</label>
            <textarea
              className="jsp-input text-xs min-h-[120px]"
              value={apply.instructions}
              onChange={(e) => setApply({ ...apply, instructions: e.target.value })}
              disabled={saving}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div>
              <label className="jsp-label">What “yes” means</label>
              <textarea
                className="jsp-input text-xs min-h-[60px]"
                value={apply.criteria_true}
                onChange={(e) => setApply({ ...apply, criteria_true: e.target.value })}
                disabled={saving}
              />
            </div>
            <div>
              <label className="jsp-label">What “no” means</label>
              <textarea
                className="jsp-input text-xs min-h-[60px]"
                value={apply.criteria_false}
                onChange={(e) => setApply({ ...apply, criteria_false: e.target.value })}
                disabled={saving}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="flex items-center gap-1.5">
              GO at ≥
              <input
                type="number"
                min={1}
                max={100}
                className="jsp-input text-xs py-1 w-20"
                style={{ width: "5rem" }}
                value={Math.round(apply.go_threshold * 100)}
                onChange={(e) =>
                  setApply({ ...apply, go_threshold: Math.min(1, Math.max(0, Number(e.target.value) / 100)) })
                }
                disabled={saving}
              />
              %
            </label>
            <label className="flex items-center gap-1.5">
              NO-GO at ≤
              <input
                type="number"
                min={0}
                max={99}
                className="jsp-input text-xs py-1 w-20"
                style={{ width: "5rem" }}
                value={Math.round(apply.nogo_threshold * 100)}
                onChange={(e) =>
                  setApply({ ...apply, nogo_threshold: Math.min(1, Math.max(0, Number(e.target.value) / 100)) })
                }
                disabled={saving}
              />
              %
            </label>
            {apply.nogo_threshold >= apply.go_threshold ? (
              <span className="text-corp-danger">NO-GO must be below GO.</span>
            ) : null}
          </div>
          <div className="text-[11px] text-corp-muted">
            Blocked industries Jev treats as a hard no:{" "}
            {blockedIndustries.length ? (
              <span className="text-corp-text">{blockedIndustries.join(", ")}</span>
            ) : (
              <span>none</span>
            )}{" "}
            — edit them on Settings → Criteria List (category Industry, tier unacceptable).
          </div>
        </div>
      ) : null}

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

      {emailQs.length ? (
        <div className="jsp-card p-4 space-y-2">
          <h4 className="text-sm font-medium">Email triage questions</h4>
          <p className="text-[11px] text-corp-muted">
            When Gmail import (or a pasted email) is classified, Jev answers one yes/no
            question per email type — &ldquo;Does this email belong in this category?&rdquo;
            plus the text below. A confident answer with a clear job match skips the LLM.
          </p>
          {emailQs.map((q, i) => (
            <div key={q.key} className="space-y-0.5">
              <div className="flex items-center gap-2">
                <label className="jsp-label !mb-0">{q.label}</label>
                {q.text.trim() !== q.default ? (
                  <button
                    type="button"
                    className="text-[11px] text-corp-accent hover:underline ml-auto"
                    onClick={() =>
                      setEmailQs(emailQs.map((x, j) => (j === i ? { ...x, text: x.default } : x)))
                    }
                    disabled={saving}
                  >
                    reset
                  </button>
                ) : null}
              </div>
              <textarea
                className="jsp-input text-xs min-h-[44px]"
                value={q.text}
                onChange={(e) =>
                  setEmailQs(emailQs.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))
                }
                disabled={saving}
              />
            </div>
          ))}
        </div>
      ) : null}

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
