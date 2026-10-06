"use client";

// Settings → Prompts: edit the prompt behind every agent action and run
// A/B experiments. Each prompt has the built-in default plus custom
// variants; every enabled variant gets traffic in proportion to its
// weight. Document prompts show a per-variant outcome scoreboard.

import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";

type PromptListItem = {
  key: string;
  label: string;
  group: string;
  description: string;
  tracks_documents: boolean;
  variant_count: number;
  customized: boolean;
  ab_testing: boolean;
};

type Variant = {
  id: string | null;
  name: string;
  template: string;
  enabled: boolean;
  weight: number;
  builtin: boolean;
  share?: number;
};

type PromptDetail = {
  key: string;
  label: string;
  description: string;
  tracks_documents: boolean;
  placeholders: string[];
  variants: Variant[];
  // Slot cap, built-in default included.
  max_variants?: number;
};

type StatRow = {
  variant_id: string;
  name: string;
  documents: number;
  jobs: number;
  applied: number;
  responded: number;
  interviewed: number;
  offered: number;
  response_rate: number | null;
  interview_rate: number | null;
  offer_rate: number | null;
  small_sample: boolean;
};

type Preview = {
  rendered: string;
  missing_placeholders: string[];
  unknown_placeholders: string[];
};

// Server's explanation (e.g. the slot cap) rather than a generic guess.
function errText(e: ApiError): string {
  return typeof e.detail === "string" ? e.detail : e.info?.message ?? `HTTP ${e.status}`;
}

const pct = (r: number | null) => (r == null ? "—" : `${Math.round(r * 100)}%`);

export function PromptsPanel() {
  const [list, setList] = useState<PromptListItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<PromptDetail | null>(null);
  const [stats, setStats] = useState<StatRow[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [previews, setPreviews] = useState<Record<number, Preview | null>>({});

  async function loadList() {
    try {
      const out = await api.get<{ prompts: PromptListItem[] }>("/api/v1/prompts");
      setList(out.prompts);
    } catch {
      setMsg("Could not load prompts.");
    }
  }
  useEffect(() => {
    void loadList();
  }, []);

  async function open(key: string) {
    if (dirty && !window.confirm("Discard unsaved changes?")) return;
    setSelected(key);
    setDetail(null);
    setStats(null);
    setPreviews({});
    setDirty(false);
    setMsg(null);
    try {
      const d = await api.get<PromptDetail>(`/api/v1/prompts/${key}`);
      setDetail(d);
      if (d.tracks_documents) {
        const s = await api.get<{ variants: StatRow[] }>(`/api/v1/prompts/${key}/stats`);
        setStats(s.variants);
      }
    } catch {
      setMsg("Could not load that prompt.");
    }
  }

  function patch(i: number, p: Partial<Variant>) {
    setDetail((d) =>
      d ? { ...d, variants: d.variants.map((v, j) => (j === i ? { ...v, ...p } : v)) } : d,
    );
    setDirty(true);
    setMsg(null);
  }

  function addVariant(fromIndex: number) {
    if (!detail) return;
    const src = detail.variants[fromIndex];
    setDetail({
      ...detail,
      variants: [
        ...detail.variants,
        {
          id: null,
          name: `${src.builtin ? "Variant" : src.name} copy`,
          template: src.template,
          enabled: true,
          weight: 1,
          builtin: false,
        },
      ],
    });
    setDirty(true);
  }

  async function removeVariant(i: number) {
    if (!detail) return;
    const v = detail.variants[i];
    // Never saved: just drop it from the editor.
    if (!v.id) {
      setDetail({ ...detail, variants: detail.variants.filter((_, j) => j !== i) });
      setPreviews({});
      return;
    }
    if (
      !window.confirm(
        `Permanently delete "${v.name}"? This frees its slot. Documents it already wrote keep their attribution.`,
      )
    )
      return;
    setSaving(true);
    setMsg(null);
    try {
      const out = await api.delete<PromptDetail>(
        `/api/v1/prompts/${detail.key}/variants/${encodeURIComponent(v.id)}`,
      );
      // Drop just that variant locally so other unsaved edits survive.
      setDetail((d) =>
        d
          ? {
              ...d,
              max_variants: out?.max_variants ?? d.max_variants,
              variants: d.variants.filter((x) => x.id !== v.id),
            }
          : d,
      );
      setPreviews({});
      setMsg(`Deleted "${v.name}" — slot freed.`);
      void loadList();
    } catch (e) {
      setMsg(e instanceof ApiError ? `Delete failed: ${errText(e)}` : "Delete failed.");
    } finally {
      setSaving(false);
    }
  }

  async function preview(i: number) {
    if (!detail) return;
    try {
      const out = await api.post<Preview>(`/api/v1/prompts/${detail.key}/preview`, {
        template: detail.variants[i].template,
      });
      setPreviews((p) => ({ ...p, [i]: out }));
    } catch {
      setMsg("Preview failed.");
    }
  }

  async function save() {
    if (!detail) return;
    setSaving(true);
    setMsg(null);
    try {
      const out = await api.put<PromptDetail>(`/api/v1/prompts/${detail.key}`, {
        variants: detail.variants.map((v) => ({
          id: v.builtin ? "default" : v.id,
          name: v.name,
          template: v.builtin ? null : v.template,
          enabled: v.enabled,
          weight: v.weight,
        })),
      });
      setDetail(out);
      setDirty(false);
      setPreviews({});
      setMsg("Saved — takes effect on the next run.");
      void loadList();
    } catch (e) {
      setMsg(
        e instanceof ApiError
          ? `Save failed: ${errText(e)}`
          : "Save failed.",
      );
    } finally {
      setSaving(false);
    }
  }

  const groups = useMemo(() => {
    const g: Record<string, PromptListItem[]> = {};
    for (const p of list) (g[p.group] ??= []).push(p);
    return Object.entries(g);
  }, [list]);

  const maxSlots = detail?.max_variants ?? 12;
  const atCap = detail ? detail.variants.length >= maxSlots : false;

  const activeCount = detail
    ? detail.variants.filter((v) => v.enabled && v.weight > 0).length
    : 0;
  const totalWeight = detail
    ? detail.variants
        .filter((v) => v.enabled && v.weight > 0)
        .reduce((s, v) => s + v.weight, 0)
    : 0;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-4">
      <div className="jsp-card p-3 space-y-3 h-fit">
        <p className="text-xs text-corp-muted">
          Every agent action&apos;s prompt. Add variants to tweak one, or leave
          several enabled to A/B test them.
        </p>
        {groups.map(([group, items]) => (
          <div key={group}>
            <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
              {group}
            </div>
            <ul className="space-y-0.5">
              {items.map((p) => (
                <li key={p.key}>
                  <button
                    type="button"
                    onClick={() => void open(p.key)}
                    className={`w-full text-left text-sm px-2 py-1 rounded flex items-center gap-1.5 ${
                      selected === p.key
                        ? "bg-corp-accent/15 text-corp-accent"
                        : "hover:bg-corp-surface2"
                    }`}
                  >
                    <span className="truncate flex-1">{p.label}</span>
                    {p.ab_testing ? (
                      <span className="text-[9px] uppercase px-1 rounded border border-corp-accent2/50 text-corp-accent2">
                        A/B
                      </span>
                    ) : p.customized ? (
                      <span className="text-[9px] uppercase px-1 rounded border border-corp-accent/50 text-corp-accent">
                        custom
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="space-y-4 min-w-0">
        {!selected ? (
          <div className="jsp-card p-6 text-sm text-corp-muted">
            Pick a prompt on the left. Resume and cover-letter prompts show an
            outcome scoreboard per variant, so you can see which version gets
            more responses and interviews.
          </div>
        ) : !detail ? (
          <div className="jsp-card p-6 text-sm text-corp-muted">{msg ?? "Loading…"}</div>
        ) : (
          <>
            <div className="jsp-card p-4 space-y-2">
              <h3 className="text-base font-semibold">{detail.label}</h3>
              {detail.description ? (
                <p className="text-xs text-corp-muted">{detail.description}</p>
              ) : null}
              <div className="flex flex-wrap gap-1 items-center">
                <span className="text-[10px] uppercase tracking-wider text-corp-muted mr-1">
                  Placeholders
                </span>
                {detail.placeholders.map((p) => (
                  <code
                    key={p}
                    className="text-[11px] px-1.5 py-0.5 rounded bg-corp-surface2 border border-corp-border"
                  >
                    {`{${p}}`}
                  </code>
                ))}
              </div>
              <p className="text-[11px] text-corp-muted">
                Write <code>{"{{"}</code> / <code>{"}}"}</code> for literal braces (e.g. JSON
                examples). {activeCount > 1
                  ? `A/B test running across ${activeCount} variants.`
                  : activeCount === 0
                    ? "Nothing enabled — the built-in default will be used."
                    : "One variant active."}
              </p>
              <p className={`text-[11px] ${atCap ? "text-corp-accent2" : "text-corp-muted"}`}>
                Slots used: {detail.variants.length} / {maxSlots} (built-in default
                included).{" "}
                {atCap
                  ? "Full — delete a variant to make room. Disabling doesn't free a slot."
                  : "Deleting a variant frees its slot; disabling keeps it."}
              </p>
            </div>

            {stats && stats.length > 0 ? (
              <div className="jsp-card p-4 overflow-x-auto">
                <h4 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
                  Scoreboard
                </h4>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-corp-muted">
                      <th className="py-1 pr-3 font-normal">Variant</th>
                      <th className="py-1 pr-3 font-normal">Docs</th>
                      <th className="py-1 pr-3 font-normal">Applied</th>
                      <th className="py-1 pr-3 font-normal">Response</th>
                      <th className="py-1 pr-3 font-normal">Interview</th>
                      <th className="py-1 pr-3 font-normal">Offer</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.map((s) => (
                      <tr key={s.variant_id} className="border-t border-corp-border">
                        <td className="py-1 pr-3">
                          {s.name}
                          {s.small_sample ? (
                            <span
                              className="ml-1 text-[9px] text-corp-muted"
                              title="Fewer than 20 applied jobs — differences are likely noise."
                            >
                              (small sample)
                            </span>
                          ) : null}
                        </td>
                        <td className="py-1 pr-3">{s.documents}</td>
                        <td className="py-1 pr-3">{s.applied}</td>
                        <td className="py-1 pr-3">
                          {pct(s.response_rate)}{" "}
                          <span className="text-corp-muted">({s.responded})</span>
                        </td>
                        <td className="py-1 pr-3">
                          {pct(s.interview_rate)}{" "}
                          <span className="text-corp-muted">({s.interviewed})</span>
                        </td>
                        <td className="py-1 pr-3">
                          {pct(s.offer_rate)}{" "}
                          <span className="text-corp-muted">({s.offered})</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[11px] text-corp-muted mt-2">
                  Each job counts for the variant of its newest document from this
                  prompt (the one Apply downloads). Rates are out of jobs that reached
                  Applied or later, using each job&apos;s current status.
                </p>
              </div>
            ) : null}

            {detail.variants.map((v, i) => {
              const share =
                v.enabled && v.weight > 0 && totalWeight > 0 ? v.weight / totalWeight : 0;
              const pv = previews[i];
              return (
                <div key={v.id ?? `new-${i}`} className="jsp-card p-4 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {v.builtin ? (
                      <span className="text-sm font-medium">Built-in default</span>
                    ) : (
                      <input
                        className="jsp-input text-sm py-1 w-56"
                        value={v.name}
                        onChange={(e) => patch(i, { name: e.target.value })}
                        disabled={saving}
                      />
                    )}
                    {v.id && !v.builtin ? (
                      <code className="text-[10px] text-corp-muted" title="Variant id">
                        {v.id}
                      </code>
                    ) : null}
                    <label className="text-xs flex items-center gap-1 text-corp-muted ml-auto">
                      <input
                        type="checkbox"
                        className="accent-corp-accent"
                        checked={v.enabled}
                        onChange={(e) => patch(i, { enabled: e.target.checked })}
                        disabled={saving}
                      />
                      Enabled
                    </label>
                    <label className="text-xs flex items-center gap-1 text-corp-muted">
                      Weight
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={0.5}
                        className="jsp-input text-xs py-1 w-16"
                        value={v.weight}
                        onChange={(e) =>
                          patch(i, { weight: Math.max(0, Number(e.target.value) || 0) })
                        }
                        disabled={saving}
                      />
                    </label>
                    <span className="text-xs text-corp-accent w-12 text-right">
                      {Math.round(share * 100)}%
                    </span>
                  </div>
                  <textarea
                    className="jsp-input font-mono text-[11px] min-h-[220px]"
                    value={v.template}
                    readOnly={v.builtin}
                    onChange={(e) => patch(i, { template: e.target.value })}
                    disabled={saving}
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="jsp-btn-ghost text-xs"
                      onClick={() => addVariant(i)}
                      disabled={saving || atCap}
                      title={atCap ? `All ${maxSlots} slots used — delete a variant first.` : undefined}
                    >
                      Duplicate as new variant
                    </button>
                    {!v.builtin ? (
                      <>
                        <button
                          type="button"
                          className="jsp-btn-ghost text-xs"
                          onClick={() => void preview(i)}
                          disabled={saving}
                        >
                          Check placeholders
                        </button>
                        <button
                          type="button"
                          className="jsp-btn-ghost text-xs text-corp-danger border-corp-danger/40"
                          onClick={() => void removeVariant(i)}
                          disabled={saving}
                        >
                          Delete
                        </button>
                      </>
                    ) : null}
                  </div>
                  {pv ? (
                    <div className="text-[11px] space-y-1">
                      {pv.missing_placeholders.length ? (
                        <p className="text-corp-accent2">
                          Not used (the default uses these):{" "}
                          {pv.missing_placeholders.map((p) => `{${p}}`).join(", ")}
                        </p>
                      ) : null}
                      {pv.unknown_placeholders.length ? (
                        <p className="text-corp-danger">
                          Unknown — will stay as literal text:{" "}
                          {pv.unknown_placeholders.map((p) => `{${p}}`).join(", ")}
                        </p>
                      ) : null}
                      {!pv.missing_placeholders.length && !pv.unknown_placeholders.length ? (
                        <p className="text-corp-ok">All placeholders check out.</p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}

            <div className="flex items-center gap-3 sticky bottom-2">
              <button
                type="button"
                className="jsp-btn-primary"
                onClick={() => void save()}
                disabled={saving || !dirty}
              >
                {saving ? "Saving…" : "Save prompt"}
              </button>
              {msg ? <span className="text-xs text-corp-muted">{msg}</span> : null}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
