"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";
import type { TimelineEvent } from "@/lib/types";

type Kind = TimelineEvent["kind"];

type KindStyle = {
  label: string;
  bar: string;          // background for bar / marker
  border: string;       // border accent
  chip: string;         // legend pill
};

const KIND_STYLES: Record<Kind, KindStyle> = {
  work: {
    label: "Work",
    bar: "bg-corp-accent/85 hover:bg-corp-accent",
    border: "border-l-corp-accent",
    chip: "bg-corp-accent/25 text-corp-accent",
  },
  education: {
    label: "Education",
    bar: "bg-sky-500/80 hover:bg-sky-400",
    border: "border-l-sky-400",
    chip: "bg-sky-500/25 text-sky-300",
  },
  course: {
    label: "Course",
    bar: "bg-sky-300/70 hover:bg-sky-300",
    border: "border-l-sky-300",
    chip: "bg-sky-300/25 text-sky-200",
  },
  certification: {
    label: "Certification",
    bar: "bg-emerald-500/80 hover:bg-emerald-400",
    border: "border-l-emerald-400",
    chip: "bg-emerald-500/25 text-emerald-300",
  },
  project: {
    label: "Project",
    bar: "bg-violet-500/80 hover:bg-violet-400",
    border: "border-l-violet-400",
    chip: "bg-violet-500/25 text-violet-300",
  },
  publication: {
    label: "Publication",
    bar: "bg-rose-500/80 hover:bg-rose-400",
    border: "border-l-rose-400",
    chip: "bg-rose-500/25 text-rose-300",
  },
  presentation: {
    label: "Presentation",
    bar: "bg-pink-500/80 hover:bg-pink-400",
    border: "border-l-pink-400",
    chip: "bg-pink-500/25 text-pink-300",
  },
  achievement: {
    label: "Achievement",
    bar: "bg-corp-accent2/80 hover:bg-corp-accent2",
    border: "border-l-corp-accent2",
    chip: "bg-corp-accent2/25 text-corp-accent2",
  },
  volunteer: {
    label: "Volunteer",
    bar: "bg-teal-500/80 hover:bg-teal-400",
    border: "border-l-teal-400",
    chip: "bg-teal-500/25 text-teal-300",
  },
  custom: {
    label: "Custom",
    bar: "bg-corp-muted/70 hover:bg-corp-muted",
    border: "border-l-corp-muted",
    chip: "bg-corp-muted/25 text-corp-muted",
  },
};

const KIND_DISPLAY_ORDER: Kind[] = [
  "work",
  "education",
  "course",
  "project",
  "publication",
  "presentation",
  "certification",
  "achievement",
  "volunteer",
  "custom",
];

type PositionedEvent = TimelineEvent & {
  startMs: number;
  endMs: number;
  isPoint: boolean;
  isOngoing: boolean;
};

function toMillis(s: string | null | undefined, fallback: number): number {
  if (!s) return fallback;
  const d = new Date(s);
  return isNaN(d.getTime()) ? fallback : d.getTime();
}

function positionEvent(ev: TimelineEvent, nowMs: number): PositionedEvent | null {
  const hasStart = !!ev.start_date;
  const hasEnd = !!ev.end_date;
  if (!hasStart && !hasEnd) return null; // undated — render separately

  const startMs = toMillis(ev.start_date, toMillis(ev.end_date, nowMs));
  const endMs = hasEnd ? toMillis(ev.end_date, startMs) : nowMs;
  const isOngoing = hasStart && !hasEnd;
  const isPoint = hasStart && hasEnd && ev.start_date === ev.end_date;

  return {
    ...ev,
    startMs,
    endMs: Math.max(endMs, startMs),
    isPoint,
    isOngoing,
  };
}

function assignLanes(events: PositionedEvent[]): PositionedEvent[][] {
  // Sort by start ascending, then by length descending (longer events claim
  // lanes first). Then pack with two passes:
  //   1. Prefer lanes whose last event shares the same subtitle (org) —
  //      promotions / back-to-school-after-same-school inline naturally.
  //   2. Otherwise fall back to the first lane that can fit.
  //
  // Gap tolerance: events with up to 60 days of gap are allowed to share a
  // lane. Covers "intern ends June, full-time starts August" without also
  // smashing unrelated years-apart events together.
  const sorted = [...events].sort(
    (a, b) => a.startMs - b.startMs || b.endMs - b.startMs - (a.endMs - a.startMs),
  );
  const lanes: PositionedEvent[][] = [];
  const GAP_DAYS = 60;
  const GAP_MS = GAP_DAYS * 24 * 3600 * 1000;
  for (const ev of sorted) {
    let placed = false;
    // First pass: same-subtitle preference.
    if (ev.subtitle) {
      for (const lane of lanes) {
        const last = lane[lane.length - 1];
        if (
          last.subtitle === ev.subtitle &&
          ev.startMs > last.endMs - GAP_MS  // allow slight overlap / tight adjacency
        ) {
          lane.push(ev);
          placed = true;
          break;
        }
      }
    }
    // Second pass: any lane with a strictly non-overlapping tail.
    if (!placed) {
      for (const lane of lanes) {
        const last = lane[lane.length - 1];
        if (ev.startMs > last.endMs + 24 * 3600 * 1000) {
          lane.push(ev);
          placed = true;
          break;
        }
      }
    }
    if (!placed) lanes.push([ev]);
  }
  return lanes;
}

function axisYears(minMs: number, maxMs: number): number[] {
  const start = new Date(minMs).getFullYear();
  const end = new Date(maxMs).getFullYear();
  const out: number[] = [];
  for (let y = start; y <= end; y++) out.push(y);
  return out;
}

function pct(ms: number, minMs: number, maxMs: number): number {
  if (maxMs <= minMs) return 0;
  return ((ms - minMs) / (maxMs - minMs)) * 100;
}

function formatRange(ev: PositionedEvent): string {
  const s = ev.start_date ?? "?";
  const e = ev.isOngoing ? "present" : (ev.end_date ?? s);
  return `${s} → ${e}`;
}

export default function TimelinePage() {
  const router = useRouter();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [enabledKinds, setEnabledKinds] = useState<Set<Kind>>(
    () => new Set(KIND_DISPLAY_ORDER),
  );
  // Visible date range controls. `null` on either side means "unbounded on
  // that side" — we fall back to the data's own extent. The "Fit to content"
  // button resets both to null.
  const [fromYear, setFromYear] = useState<number | null>(null);
  const [toYear, setToYear] = useState<number | null>(null);
  const [onlyGaps, setOnlyGaps] = useState(false);
  const [groupMode, setGroupMode] = useState<"kind" | "org">("kind");

  useEffect(() => {
    api
      .get<TimelineEvent[]>("/api/v1/history/timeline")
      .then((ev) => {
        setEvents(ev);
        setLoading(false);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        } else {
          setLoading(false);
        }
      });
  }, [router]);

  const nowMs = useMemo(() => Date.now(), []);

  // Natural extent from the data — used for axis boundaries when no explicit
  // range is set, and to drive the from/to year selectors.
  const { dataMin, dataMax, dataMinYear, dataMaxYear } = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const ev of events) {
      const pos = positionEvent(ev, nowMs);
      if (!pos) continue;
      min = Math.min(min, pos.startMs);
      max = Math.max(max, pos.endMs);
    }
    if (!isFinite(min)) {
      min = nowMs - 365 * 24 * 3600 * 1000;
      max = nowMs;
    }
    const minY = new Date(min).getFullYear();
    const maxY = new Date(max).getFullYear();
    return { dataMin: min, dataMax: max, dataMinYear: minY, dataMaxYear: maxY };
  }, [events, nowMs]);

  const { byKind, undated, minMs, maxMs } = useMemo(() => {
    const byKind: Partial<Record<Kind, PositionedEvent[]>> = {};
    const undated: TimelineEvent[] = [];
    // Effective visible window: user-set years win; else the data extent.
    const visibleFromMs =
      fromYear != null ? new Date(fromYear, 0, 1).getTime() : dataMin;
    const visibleToMs =
      toYear != null
        ? new Date(toYear + 1, 0, 1).getTime() - 1
        : dataMax;

    for (const ev of events) {
      const pos = positionEvent(ev, nowMs);
      if (!pos) {
        undated.push(ev);
        continue;
      }
      // Keep events that overlap the visible window at all (so a multi-year
      // role that started before `from` still shows its relevant portion).
      if (pos.endMs < visibleFromMs || pos.startMs > visibleToMs) continue;
      if (onlyGaps) {
        const gaps = (ev.metadata as { gaps?: string[] } | null | undefined)?.gaps ?? [];
        if (gaps.length === 0) continue;
      }
      (byKind[pos.kind] ??= []).push(pos);
    }

    // Pad each side by 3% so events don't hug the axis edges.
    let min = visibleFromMs;
    let max = visibleToMs;
    const span = max - min || 365 * 24 * 3600 * 1000;
    min -= span * 0.03;
    max += span * 0.03;
    return { byKind, undated, minMs: min, maxMs: max };
  }, [events, nowMs, fromYear, toYear, dataMin, dataMax, onlyGaps]);

  // Organization-grouped view: one row per unique subtitle (typically org /
  // issuer / venue). Events without a subtitle collect under "Unaffiliated".
  const byOrg = useMemo(() => {
    const groups = new Map<string, PositionedEvent[]>();
    for (const list of Object.values(byKind)) {
      if (!list) continue;
      for (const ev of list) {
        // Prefer an explicit effective_org set by the backend (e.g. a
        // project's linked job org) so cross-kind links gather properly.
        const effective =
          (ev.metadata as { effective_org?: string | null } | null | undefined)
            ?.effective_org ?? null;
        const key = (effective || ev.subtitle)?.trim() || "Unaffiliated";
        const arr = groups.get(key);
        if (arr) arr.push(ev);
        else groups.set(key, [ev]);
      }
    }
    return Array.from(groups.entries()).sort((a, b) => {
      // "Unaffiliated" pinned last; otherwise alphabetical.
      if (a[0] === "Unaffiliated") return 1;
      if (b[0] === "Unaffiliated") return -1;
      return a[0].localeCompare(b[0]);
    });
  }, [byKind]);

  const totalGaps = useMemo(
    () =>
      events.filter(
        (e) =>
          ((e.metadata as { gaps?: string[] } | null | undefined)?.gaps ?? [])
            .length > 0,
      ).length,
    [events],
  );

  const kindsPresent = KIND_DISPLAY_ORDER.filter(
    (k) => (byKind[k]?.length ?? 0) > 0,
  );

  const fitToContent = () => {
    setFromYear(null);
    setToYear(null);
  };

  const isZoomed = fromYear != null || toYear != null;

  function toggleKind(k: Kind) {
    setEnabledKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  return (
    <PageShell
      title="Career Timeline"
      subtitle="A horizontal record of every dated event. Parallel engagements stack into lanes; point events render as markers."
    >
      {loading ? (
        <p className="text-corp-muted">Retrieving chronology...</p>
      ) : kindsPresent.length === 0 ? (
        <div className="jsp-card p-6 text-corp-muted text-sm">
          No dated events recorded yet. Add entries on the{" "}
          <a href="/history" className="text-corp-accent hover:underline">History Editor</a>.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-3 items-end justify-between">
            <Legend
              kinds={kindsPresent}
              enabled={enabledKinds}
              onToggle={toggleKind}
            />
            <div className="flex gap-3 items-end">
              <div className="inline-flex rounded-md border border-corp-border overflow-hidden">
                <button
                  type="button"
                  onClick={() => setGroupMode("kind")}
                  className={`px-2.5 py-1 text-xs uppercase tracking-wider ${
                    groupMode === "kind"
                      ? "bg-corp-accent/25 text-corp-accent"
                      : "bg-corp-surface2 text-corp-muted hover:text-corp-text"
                  }`}
                  title="Group rows by kind (work / education / project / ...)"
                >
                  By kind
                </button>
                <button
                  type="button"
                  onClick={() => setGroupMode("org")}
                  className={`px-2.5 py-1 text-xs uppercase tracking-wider border-l border-corp-border ${
                    groupMode === "org"
                      ? "bg-corp-accent/25 text-corp-accent"
                      : "bg-corp-surface2 text-corp-muted hover:text-corp-text"
                  }`}
                  title="Group rows by organization / issuer"
                >
                  By org
                </button>
              </div>
              <button
                type="button"
                onClick={() => setOnlyGaps((v) => !v)}
                className={`px-2.5 py-1 rounded-md text-xs uppercase tracking-wider border transition-opacity ${
                  onlyGaps
                    ? "bg-corp-accent2/20 text-corp-accent2 border-corp-accent2/40"
                    : "bg-corp-surface2 text-corp-muted border-corp-border hover:text-corp-text"
                }`}
                title={
                  onlyGaps
                    ? "Showing only entries with missing fields"
                    : `Toggle to show only the ${totalGaps} entr${
                        totalGaps === 1 ? "y" : "ies"
                      } with missing fields`
                }
                disabled={totalGaps === 0}
              >
                ⚠ gaps {totalGaps > 0 ? `(${totalGaps})` : ""}
              </button>
              <RangeControls
                fromYear={fromYear}
                toYear={toYear}
                dataMinYear={dataMinYear}
                dataMaxYear={dataMaxYear}
                onFrom={setFromYear}
                onTo={setToYear}
                onFit={fitToContent}
                isZoomed={isZoomed}
              />
            </div>
          </div>

          <div className="jsp-card p-4 mt-4 overflow-x-auto">
            <div className="min-w-[48rem]">
              <YearAxis minMs={minMs} maxMs={maxMs} nowMs={nowMs} />
              <div className="space-y-4 mt-2">
                {groupMode === "kind"
                  ? kindsPresent
                      .filter((k) => enabledKinds.has(k))
                      .map((k) => (
                        <KindRow
                          key={k}
                          kind={k}
                          events={byKind[k] ?? []}
                          minMs={minMs}
                          maxMs={maxMs}
                        />
                      ))
                  : byOrg
                      .map(([org, evs]) => [
                        org,
                        evs.filter((e) => enabledKinds.has(e.kind)),
                      ] as const)
                      .filter(([, evs]) => evs.length > 0)
                      .map(([org, evs]) => (
                        <OrgRow
                          key={org}
                          org={org}
                          events={evs}
                          minMs={minMs}
                          maxMs={maxMs}
                        />
                      ))}
              </div>
            </div>
          </div>

          {undated.length > 0 ? (
            <div className="jsp-card p-4 mt-4">
              <h3 className="text-sm uppercase tracking-wider text-corp-muted mb-2">
                Undated
              </h3>
              <ul className="space-y-1 text-sm">
                {undated.map((u) => (
                  <li key={`${u.kind}-${u.id}`}>
                    <span className="text-xs uppercase tracking-wider text-corp-muted mr-2">
                      {u.kind}
                    </span>
                    {u.title}
                    {u.subtitle ? (
                      <span className="text-corp-muted"> · {u.subtitle}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </PageShell>
  );
}

function RangeControls({
  fromYear,
  toYear,
  dataMinYear,
  dataMaxYear,
  onFrom,
  onTo,
  onFit,
  isZoomed,
}: {
  fromYear: number | null;
  toYear: number | null;
  dataMinYear: number;
  dataMaxYear: number;
  onFrom: (y: number | null) => void;
  onTo: (y: number | null) => void;
  onFit: () => void;
  isZoomed: boolean;
}) {
  // Offer a year picker that spans a bit beyond the actual data range so
  // users can project into recent history or future plans.
  const pad = 2;
  const lo = dataMinYear - pad;
  const hi = Math.max(dataMaxYear, new Date().getFullYear()) + pad;
  const years: number[] = [];
  for (let y = lo; y <= hi; y++) years.push(y);

  return (
    <div className="flex gap-2 items-end">
      <div>
        <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
          From
        </div>
        <select
          className="jsp-input text-sm py-1"
          value={fromYear ?? ""}
          onChange={(e) =>
            onFrom(e.target.value === "" ? null : Number(e.target.value))
          }
        >
          <option value="">all</option>
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-corp-muted mb-1">
          To
        </div>
        <select
          className="jsp-input text-sm py-1"
          value={toYear ?? ""}
          onChange={(e) =>
            onTo(e.target.value === "" ? null : Number(e.target.value))
          }
        >
          <option value="">present</option>
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>
      <button
        type="button"
        className="jsp-btn-ghost text-xs"
        onClick={onFit}
        disabled={!isZoomed}
        title="Reset to full date range"
      >
        Fit to content
      </button>
    </div>
  );
}


function Legend({
  kinds,
  enabled,
  onToggle,
}: {
  kinds: Kind[];
  enabled: Set<Kind>;
  onToggle: (k: Kind) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {kinds.map((k) => {
        const style = KIND_STYLES[k];
        const on = enabled.has(k);
        return (
          <button
            key={k}
            type="button"
            onClick={() => onToggle(k)}
            className={`px-2.5 py-1 rounded-md text-xs uppercase tracking-wider transition-opacity ${
              style.chip
            } ${on ? "" : "opacity-40 line-through"}`}
            title={on ? "Click to hide" : "Click to show"}
          >
            {style.label}
          </button>
        );
      })}
    </div>
  );
}

function YearAxis({
  minMs,
  maxMs,
  nowMs,
}: {
  minMs: number;
  maxMs: number;
  nowMs: number;
}) {
  const years = axisYears(minMs, maxMs);
  return (
    <div className="relative h-6 border-b border-corp-border">
      {years.map((y) => {
        const ms = new Date(y, 0, 1).getTime();
        if (ms < minMs || ms > maxMs) return null;
        return (
          <div
            key={y}
            className="absolute top-0 bottom-0 border-l border-corp-border/70"
            style={{ left: `${pct(ms, minMs, maxMs)}%` }}
          >
            <div className="absolute left-1 top-0.5 text-[10px] uppercase tracking-wider text-corp-muted">
              {y}
            </div>
          </div>
        );
      })}
      {nowMs >= minMs && nowMs <= maxMs ? (
        <div
          className="absolute top-0 bottom-0 border-l-2 border-corp-accent2"
          style={{ left: `${pct(nowMs, minMs, maxMs)}%` }}
          title="Today"
        />
      ) : null}
    </div>
  );
}

function KindRow({
  kind,
  events,
  minMs,
  maxMs,
}: {
  kind: Kind;
  events: PositionedEvent[];
  minMs: number;
  maxMs: number;
}) {
  const style = KIND_STYLES[kind];
  const lanes = useMemo(() => assignLanes(events), [events]);
  const LANE_HEIGHT = 28;

  return (
    <div className="flex items-start gap-3">
      <div
        className={`w-28 shrink-0 pt-1 text-[11px] uppercase tracking-wider text-corp-muted border-l-4 pl-2 ${style.border}`}
      >
        {style.label}
      </div>
      <div
        className="relative flex-1"
        style={{ height: lanes.length * LANE_HEIGHT }}
      >
        {/* faint grid to help the eye match events to years */}
        {axisYears(minMs, maxMs).map((y) => {
          const ms = new Date(y, 0, 1).getTime();
          if (ms < minMs || ms > maxMs) return null;
          return (
            <div
              key={y}
              className="absolute top-0 bottom-0 border-l border-corp-border/40"
              style={{ left: `${pct(ms, minMs, maxMs)}%` }}
            />
          );
        })}

        {lanes.map((lane, laneIdx) => (
          <div key={laneIdx} className="absolute left-0 right-0" style={{ top: laneIdx * LANE_HEIGHT, height: LANE_HEIGHT }}>
            {lane.map((ev) => (
              <EventBar key={`${ev.kind}-${ev.id}`} ev={ev} minMs={minMs} maxMs={maxMs} style={style} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function OrgRow({
  org,
  events,
  minMs,
  maxMs,
}: {
  org: string;
  events: PositionedEvent[];
  minMs: number;
  maxMs: number;
}) {
  const lanes = useMemo(() => assignLanes(events), [events]);
  const LANE_HEIGHT = 28;
  return (
    <div className="flex items-start gap-3">
      <div className="w-28 shrink-0 pt-1 text-[11px] uppercase tracking-wider text-corp-muted border-l-4 pl-2 border-corp-accent2 truncate">
        {org}
      </div>
      <div
        className="relative flex-1"
        style={{ height: lanes.length * LANE_HEIGHT }}
      >
        {axisYears(minMs, maxMs).map((y) => {
          const ms = new Date(y, 0, 1).getTime();
          if (ms < minMs || ms > maxMs) return null;
          return (
            <div
              key={y}
              className="absolute top-0 bottom-0 border-l border-corp-border/40"
              style={{ left: `${pct(ms, minMs, maxMs)}%` }}
            />
          );
        })}
        {lanes.map((lane, laneIdx) => (
          <div
            key={laneIdx}
            className="absolute left-0 right-0"
            style={{ top: laneIdx * LANE_HEIGHT, height: LANE_HEIGHT }}
          >
            {lane.map((ev) => (
              <EventBar
                key={`${ev.kind}-${ev.id}`}
                ev={ev}
                minMs={minMs}
                maxMs={maxMs}
                style={KIND_STYLES[ev.kind]}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function EventBar({
  ev,
  minMs,
  maxMs,
  style,
}: {
  ev: PositionedEvent;
  minMs: number;
  maxMs: number;
  style: KindStyle;
}) {
  const left = pct(ev.startMs, minMs, maxMs);
  const right = pct(ev.endMs, minMs, maxMs);
  const width = Math.max(right - left, 0.5);

  const gaps = (ev.metadata as { gaps?: string[] } | null | undefined)?.gaps ?? [];
  const hasGaps = gaps.length > 0;

  const label = ev.subtitle ? `${ev.title} · ${ev.subtitle}` : ev.title;
  const title = hasGaps
    ? `${label}\n${formatRange(ev)}\n⚠ ${gaps.join(", ")}`
    : `${label}\n${formatRange(ev)}`;

  if (ev.isPoint) {
    return (
      <div
        className={`absolute top-1 h-5 w-5 rotate-45 rounded-sm ${style.bar} cursor-default ${
          hasGaps ? "ring-2 ring-corp-accent2" : ""
        }`}
        style={{ left: `calc(${left}% - 10px)` }}
        title={title}
      >
        <span className="sr-only">{label}</span>
      </div>
    );
  }

  return (
    <div
      className={`absolute top-1 bottom-1 rounded ${style.bar} text-[11px] px-2 flex items-center overflow-hidden cursor-default shadow-sm ${
        hasGaps ? "ring-2 ring-corp-accent2" : ""
      }`}
      style={{ left: `${left}%`, width: `${width}%` }}
      title={title}
    >
      {hasGaps ? (
        <span className="mr-1 text-corp-bg text-[10px]" aria-hidden="true">
          ⚠
        </span>
      ) : null}
      <span className="text-corp-bg font-medium truncate">{ev.title}</span>
      {ev.isOngoing ? (
        <span className="ml-1 text-[9px] uppercase tracking-wider text-corp-bg/80">· present</span>
      ) : null}
    </div>
  );
}
