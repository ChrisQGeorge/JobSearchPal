"use client";

// THE TOWER — the job-search incremental game.
//
// Applying to jobs earns Submission Scrip, reviewing earns Diligence Chits
// (interviews → Clout, offers → Golden Handshakes, for cosmetics). Scrip &
// chits buy floors of the tower; floors produce Shareholder Value (SV)
// idle; SV buys Executive Bonuses. SV is never earned directly. While this
// page is open the whole app turns into pixel art (html[data-pixel]).

import { useCallback, useEffect, useRef, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { api, ApiError } from "@/lib/api";
import {
  ANTENNA,
  CABINET,
  COSMETIC_SPRITES,
  CRATE,
  CurrencyIcon,
  DESK,
  LAMP,
  PAMPHLETS,
  SERVER,
  Sprite,
  TABLE,
  WINDOW,
  WORKER,
  workerPalette,
  type Palette,
} from "./_sprites";

type Cost = Partial<Record<"scrip" | "chits", number>>;
type Floor = {
  id: string;
  name: string;
  theme: string;
  tagline: string;
  level: number;
  unlocked: boolean;
  unlock_at: number;
  cost: Cost;
  affordable: boolean;
  svh: number;
  next_gain_svh: number;
  dept_bonus_level: number;
  dept_bonus_cost: number;
};
type Bonus = { id: string; name: string; desc: string; level: number; cost: number };
type Cosmetic = {
  id: string;
  name: string;
  price: Partial<Record<"clout" | "handshakes", number>>;
  floor: string;
  owned: boolean;
};
type GameView = {
  balances: Record<"scrip" | "chits" | "clout" | "handshakes", number>;
  sv: number;
  lifetime_sv: number;
  svh: number;
  title: string;
  next_title: { at: number; name: string } | null;
  earn_rates: {
    scrip_per_application: number;
    chits_per_review: number;
    clout_per_interview: number;
    handshakes_per_offer: number;
  };
  floors: Floor[];
  bonuses: Bonus[];
  cosmetics: Cosmetic[];
  recent: { currency: string; amount: number; reason: string; note: string | null; at: string | null }[];
};

const CURRENCY_NAME: Record<string, string> = {
  scrip: "Submission Scrip",
  chits: "Diligence Chits",
  sv: "Shareholder Value",
  clout: "Networking Clout",
  handshakes: "Golden Handshakes",
};

const REASON_MEMO: Record<string, string> = {
  application: "Application filed",
  review: "Listing reviewed",
  interview: "Interview stage reached",
  offer: "Offer extended",
};

function fmt(n: number): string {
  if (!Number.isFinite(n)) return "0";
  const abs = Math.abs(n);
  if (abs < 1000) return abs < 10 && n % 1 !== 0 ? n.toFixed(1) : Math.floor(n).toLocaleString();
  const units = ["K", "M", "B", "T", "Qa", "Qi"];
  let v = n;
  let i = -1;
  while (Math.abs(v) >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v.toFixed(v < 10 ? 2 : v < 100 ? 1 : 0)}${units[i]}`;
}

// --- Floor themes ---------------------------------------------------------------

type Theme = {
  wall: string;
  stripe: string;
  floor: string;
  trim: string;
  suit: string;
  hair: string;
  fixtures: { map: string[]; palette: Palette; scale?: number }[];
};

const deskPal = (glow: string): Palette => ({ m: "#3a3a3a", c: glow, w: "#6b4226" });
const THEMES: Record<string, Theme> = {
  basement: {
    wall: "#3b2c24", stripe: "#33261f", floor: "#1e1611", trim: "#c8a165", suit: "#6b4f3a", hair: "#2b1d14",
    fixtures: [
      { map: CRATE, palette: { b: "#8b5a2b", k: "#c69c6d" } },
      { map: CRATE, palette: { b: "#8b5a2b", k: "#c69c6d" } },
      { map: DESK, palette: deskPal("#c8a165") },
    ],
  },
  bureau: {
    wall: "#2b3646", stripe: "#253040", floor: "#161d28", trim: "#9fb4c8", suit: "#3d4a5c", hair: "#1b1b1b",
    fixtures: [
      { map: CABINET, palette: { g: "#8d99ae", d: "#5c677d", h: "#2b2d42" } },
      { map: CABINET, palette: { g: "#8d99ae", d: "#5c677d", h: "#2b2d42" } },
      { map: DESK, palette: deskPal("#9fb4c8") },
    ],
  },
  neon: {
    wall: "#24123f", stripe: "#2e1650", floor: "#12081f", trim: "#ff4fd8", suit: "#7a2fbf", hair: "#7af8ff",
    fixtures: [
      { map: LAMP, palette: { p: "#ff4fd8", m: "#ff006e", M: "#ffbe0b", g: "#444444" } },
      { map: DESK, palette: deskPal("#7af8ff") },
      { map: LAMP, palette: { p: "#7af8ff", m: "#3a86ff", M: "#8338ec", g: "#444444" } },
    ],
  },
  crt: {
    wall: "#0b1d10", stripe: "#0e2615", floor: "#050d07", trim: "#39ff6a", suit: "#1f5130", hair: "#0a0a0a",
    fixtures: [
      { map: SERVER, palette: { r: "#1b263b", d: "#0d1b2a", a: "#39ff6a", b: "#ffb703" } },
      { map: SERVER, palette: { r: "#1b263b", d: "#0d1b2a", a: "#39ff6a", b: "#ffb703" } },
      { map: SERVER, palette: { r: "#1b263b", d: "#0d1b2a", a: "#39ff6a", b: "#ffb703" } },
    ],
  },
  pastel: {
    wall: "#4a2a3a", stripe: "#53304a", floor: "#2a1520", trim: "#ff9ab5", suit: "#b5838d", hair: "#3a2a1a",
    fixtures: [
      { map: PAMPHLETS, palette: { a: "#8d99ae", w: "#f8f9fa", p: "#ff9ab5" } },
      { map: DESK, palette: deskPal("#ff9ab5") },
    ],
  },
  mahogany: {
    wall: "#3a1d12", stripe: "#44241a", floor: "#1f0f09", trim: "#e8c468", suit: "#2b2b2b", hair: "#5a3a1a",
    fixtures: [{ map: TABLE, palette: { w: "#7f4f24", W: "#582f0e" } }],
  },
  gold: {
    wall: "#2b2416", stripe: "#352c1a", floor: "#16120a", trim: "#ffd700", suit: "#c9a227", hair: "#f5f5f5",
    fixtures: [
      { map: WINDOW, palette: { f: "#8d6e3f", s: "#1d3557", y: "#ffd60a", b: "#0b132b" } },
      { map: DESK, palette: deskPal("#ffd700") },
    ],
  },
};

const HAIRS = ["#2b1d14", "#1b1b1b", "#c9a227", "#7a3e1d", "#9e9e9e"];

// --- Page ---------------------------------------------------------------------------

export default function TowerPage() {
  const [data, setData] = useState<GameView | null>(null);
  const [fetchedAt, setFetchedAt] = useState(Date.now());
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState<string | null>(null);
  const [memo, setMemo] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Pixel-art takeover of the whole UI while this tab is open.
  useEffect(() => {
    document.documentElement.dataset.pixel = "1";
    return () => {
      delete document.documentElement.dataset.pixel;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const v = await api.get<GameView>("/api/v1/game");
      setData(v);
      setFetchedAt(Date.now());
    } catch (e) {
      setMemo({ kind: "err", text: e instanceof ApiError ? `HTTP ${e.status}` : "Tower offline." });
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  // Smooth SV ticker between server refreshes (server stays authoritative).
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, []);

  const memoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function flash(kind: "ok" | "err", text: string) {
    setMemo({ kind, text });
    if (memoTimer.current) clearTimeout(memoTimer.current);
    memoTimer.current = setTimeout(() => setMemo(null), 4500);
  }

  async function buy(path: string, label: string) {
    setBusy(path);
    try {
      const v = await api.post<GameView>(`/api/v1/game/${path}/buy`, {});
      setData(v);
      setFetchedAt(Date.now());
      flash("ok", `MEMO: ${label} approved by the Board.`);
    } catch (e) {
      flash(
        "err",
        e instanceof ApiError
          ? `MEMO: Request denied. ${typeof e.detail === "string" ? e.detail : ""}`
          : "MEMO: Request lost in the mailroom.",
      );
    } finally {
      setBusy(null);
    }
  }

  const liveSv = data ? data.sv + (data.svh * (now - fetchedAt)) / 3_600_000 : 0;
  const liveLifetime = data ? data.lifetime_sv + (data.svh * (now - fetchedAt)) / 3_600_000 : 0;

  return (
    <PageShell
      title="THE TOWER"
      subtitle="Shareholder Value is not earned. It is extracted — by the floors you fund with real job-search work."
    >
      <link
        rel="stylesheet"
        href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap"
      />
      <div className="px-boot" />

      {!data ? (
        <div className="jsp-card p-6 text-corp-muted">BOOTING CORPORATE MAINFRAME…</div>
      ) : (
        <>
          <Hud data={data} liveSv={liveSv} liveLifetime={liveLifetime} />

          {memo ? (
            <div
              className={`jsp-card p-2 mb-3 text-sm ${
                memo.kind === "ok" ? "text-corp-ok" : "text-corp-danger"
              }`}
            >
              {memo.text}
            </div>
          ) : null}

          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] gap-4">
            <TowerView data={data} liveLifetime={liveLifetime} busy={busy} onBuy={buy} />
            <div className="space-y-4">
              <BonusPanel data={data} liveSv={liveSv} busy={busy} onBuy={buy} />
              <MerchPanel data={data} busy={busy} onBuy={buy} />
              <MemoFeed data={data} />
            </div>
          </div>
        </>
      )}
    </PageShell>
  );
}

// --- HUD ----------------------------------------------------------------------------

function Hud({ data, liveSv, liveLifetime }: { data: GameView; liveSv: number; liveLifetime: number }) {
  const nt = data.next_title;
  const pct = nt ? Math.min(100, (liveLifetime / nt.at) * 100) : 100;
  return (
    <section className="space-y-3 mb-4">
      <div className="grid grid-cols-2 md:grid-cols-[2fr_1fr_1fr_1fr_1fr] gap-3">
        <div className="jsp-card p-3 col-span-2 md:col-span-1">
          <div className="flex items-center gap-2">
            <CurrencyIcon id="sv" scale={3} />
            <span className="px-head text-[9px] text-corp-muted">SHAREHOLDER VALUE</span>
          </div>
          <div className="text-3xl text-corp-accent tabular-nums leading-tight">{fmt(liveSv)}</div>
          <div className="text-sm text-corp-ok">+{fmt(data.svh)} SV / hour · never directly earnable</div>
        </div>
        {(["scrip", "chits", "clout", "handshakes"] as const).map((c) => (
          <div key={c} className="jsp-card p-3">
            <div className="flex items-center gap-2">
              <CurrencyIcon id={c} scale={3} />
              <span className="text-2xl tabular-nums">{fmt(data.balances[c])}</span>
            </div>
            <div className="text-sm text-corp-muted leading-tight">{CURRENCY_NAME[c]}</div>
          </div>
        ))}
      </div>
      <div className="jsp-card p-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <span className="text-corp-muted">RANK: </span>
          <span className="text-corp-accent">{data.title}</span>
        </div>
        {nt ? (
          <div className="flex items-center gap-2 flex-1 min-w-[200px]">
            <div className="flex-1 h-3 bg-corp-surface2 border-2 border-corp-border">
              <div className="h-full bg-corp-accent" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-sm text-corp-muted whitespace-nowrap">
              {nt.name} at {fmt(nt.at)} lifetime SV
            </span>
          </div>
        ) : null}
        <div className="text-sm text-corp-muted basis-full">
          PAYROLL: apply to a job <b className="text-corp-text">+{data.earn_rates.scrip_per_application} Scrip</b> ·
          review a job <b className="text-corp-text">+{data.earn_rates.chits_per_review} Chits</b> · interview stage{" "}
          <b className="text-corp-text">+{data.earn_rates.clout_per_interview} Clout</b> · offer{" "}
          <b className="text-corp-text">+{data.earn_rates.handshakes_per_offer} Golden Handshake</b>
        </div>
      </div>
    </section>
  );
}

// --- Tower --------------------------------------------------------------------------

function CostTag({ cost }: { cost: Cost }) {
  return (
    <span className="inline-flex items-center gap-2">
      {Object.entries(cost).map(([c, n]) => (
        <span key={c} className="inline-flex items-center gap-1">
          <CurrencyIcon id={c} scale={2} />
          {fmt(n ?? 0)}
        </span>
      ))}
    </span>
  );
}

function TowerView({
  data,
  liveLifetime,
  busy,
  onBuy,
}: {
  data: GameView;
  liveLifetime: number;
  busy: string | null;
  onBuy: (path: string, label: string) => void;
}) {
  const owned = new Set(data.cosmetics.filter((c) => c.owned).map((c) => c.id));
  const floors = [...data.floors].reverse(); // top floor first
  return (
    <section className="jsp-card p-0 overflow-hidden">
      {/* Roof */}
      <div
        className="relative h-14 flex items-end justify-center gap-6"
        style={{ background: "linear-gradient(#0b0820, #1a1440)" }}
      >
        <Sprite
          map={ANTENNA}
          palette={{ r: "#ff3b3b", g: "#6c757d" }}
          scale={4}
          style={{ animation: "px-blink 1.2s steps(2) infinite" }}
        />
        {owned.has("helipad") ? (
          <Sprite map={COSMETIC_SPRITES.helipad.map} palette={COSMETIC_SPRITES.helipad.palette} scale={3} title="Rooftop Helipad (No Helicopter)" />
        ) : null}
        <span className="absolute left-3 top-2 px-head text-[8px] text-corp-accent">
          GLOBEX-ADJACENT HOLDINGS PLC
        </span>
      </div>
      {floors.map((f) => (
        <FloorRow
          key={f.id}
          floor={f}
          data={data}
          liveLifetime={liveLifetime}
          owned={owned}
          busy={busy}
          onBuy={onBuy}
        />
      ))}
      {/* Lobby */}
      <div
        className="h-10 flex items-center justify-center px-head text-[8px] text-corp-muted"
        style={{ background: "repeating-linear-gradient(90deg,#1a1a1a 0 12px,#222 12px 24px)" }}
      >
        LOBBY · APPLICANTS WELCOME (NOT REALLY)
      </div>
    </section>
  );
}

function FloorRow({
  floor: f,
  data,
  liveLifetime,
  owned,
  busy,
  onBuy,
}: {
  floor: Floor;
  data: GameView;
  liveLifetime: number;
  owned: Set<string>;
  busy: string | null;
  onBuy: (path: string, label: string) => void;
}) {
  const th = THEMES[f.theme] ?? THEMES.bureau;
  if (!f.unlocked) {
    const pct = Math.min(100, (liveLifetime / f.unlock_at) * 100);
    return (
      <div
        className="relative border-t-4 border-black/60 p-3 min-h-[110px] flex flex-col justify-center gap-2"
        style={{
          background:
            "repeating-linear-gradient(45deg,#2a2410 0 14px,#3a3214 14px 28px)",
        }}
      >
        <div className="px-head text-[9px] text-yellow-300">UNDER CONSTRUCTION</div>
        <div className="text-corp-text">
          {f.name} — opens at {fmt(f.unlock_at)} lifetime Shareholder Value
        </div>
        <div className="h-3 bg-black/40 border-2 border-black/60 max-w-sm">
          <div className="h-full bg-yellow-400" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }
  const workers = Math.min(f.level, 5);
  const cosmetic = data.cosmetics.find((c) => c.floor === f.id && owned.has(c.id));
  const path = `floors/${f.id}`;
  const bonusPath = `bonuses/dept:${f.id}`;
  return (
    <div
      className="relative border-t-4 border-black/60 overflow-hidden"
      style={{
        background: `repeating-linear-gradient(90deg, ${th.wall} 0 18px, ${th.stripe} 18px 36px)`,
        minHeight: 196,
      }}
    >
      {/* floor strip */}
      <div className="absolute inset-x-0 bottom-0 h-4" style={{ background: th.floor, borderTop: `3px solid ${th.trim}` }} />
      {/* fixtures + cosmetic, standing on the floor */}
      <div className="absolute bottom-4 right-4 flex items-end gap-4 opacity-95">
        {cosmetic ? (
          <Sprite
            map={COSMETIC_SPRITES[cosmetic.id].map}
            palette={COSMETIC_SPRITES[cosmetic.id].palette}
            scale={3}
            title={cosmetic.name}
          />
        ) : null}
        {th.fixtures.map((fx, i) => (
          <Sprite key={i} map={fx.map} palette={fx.palette} scale={fx.scale ?? 3} />
        ))}
      </div>
      {/* the workforce */}
      <div className="absolute bottom-4 left-0 right-56 h-12 pointer-events-none">
        {Array.from({ length: workers }, (_, i) => (
          <div
            key={i}
            className="absolute bottom-0"
            style={{
              left: 14 + i * 44,
              ["--px-walk" as string]: `${60 + ((i * 47) % 90)}px`,
              animation: `px-walk ${5 + i * 1.7}s steps(${16 + i * 3}) infinite alternate`,
            }}
          >
            <div style={{ animation: `px-bob 0.6s steps(2) infinite` }}>
              <Sprite map={WORKER} palette={workerPalette(th.suit, HAIRS[i % HAIRS.length], th.trim)} scale={4} />
            </div>
          </div>
        ))}
      </div>
      {/* placard */}
      <div className="relative p-3 flex flex-wrap items-start gap-3">
        <div className="bg-black/55 border-2 border-black/70 px-2 py-1 max-w-[30rem]">
          <div className="px-head text-[9px]" style={{ color: th.trim }}>
            {f.name.toUpperCase()}
          </div>
          <div className="text-sm text-corp-text">
            {f.level > 0 ? (
              <>
                LV {f.level} · <span className="text-corp-ok">{fmt(f.svh)} SV/h</span>
                {f.dept_bonus_level ? ` · dept bonus ×${f.dept_bonus_level}` : ""}
              </>
            ) : (
              <span className="text-corp-muted">VACANT — fund it to hire staff</span>
            )}
          </div>
          <div className="text-[13px] leading-tight text-corp-muted">{f.tagline}</div>
        </div>
        <div className="ml-auto flex flex-col items-end gap-1">
          <button
            type="button"
            className="jsp-btn-primary"
            disabled={!f.affordable || busy !== null}
            onClick={() => onBuy(path, `${f.name} expansion`)}
            title={`+${fmt(f.next_gain_svh)} SV/h`}
          >
            {busy === path ? "…" : f.level ? "EXPAND" : "FUND"}&nbsp;
            <CostTag cost={f.cost} />
          </button>
          <span className="text-[13px] text-corp-ok bg-black/50 px-1">+{fmt(f.next_gain_svh)} SV/h</span>
          {f.level > 0 ? (
            <button
              type="button"
              className="jsp-btn-ghost bg-black/40"
              disabled={busy !== null || data.sv < f.dept_bonus_cost}
              onClick={() => onBuy(bonusPath, `Departmental Bonus (${f.name})`)}
              title="Departmental Bonus: +25% this floor's output, permanently"
            >
              {busy === bonusPath ? "…" : "DEPT BONUS"}&nbsp;
              <span className="inline-flex items-center gap-1">
                <CurrencyIcon id="sv" scale={2} />
                {fmt(f.dept_bonus_cost)}
              </span>
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// --- Side panels ----------------------------------------------------------------------

function BonusPanel({
  data,
  liveSv,
  busy,
  onBuy,
}: {
  data: GameView;
  liveSv: number;
  busy: string | null;
  onBuy: (path: string, label: string) => void;
}) {
  return (
    <section className="jsp-card p-3 space-y-2">
      <h2 className="text-corp-accent">EXECUTIVE COMPENSATION COMMITTEE</h2>
      <p className="text-sm text-corp-muted leading-tight">
        Permanent bonuses, paid in Shareholder Value. Each level costs exponentially more — as is
        tradition.
      </p>
      {data.bonuses.map((b) => {
        const path = `bonuses/${b.id}`;
        return (
          <div key={b.id} className="border-2 border-corp-border p-2 space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-corp-text">{b.name}</span>
              <span className="ml-auto text-sm text-corp-muted">LV {b.level}</span>
            </div>
            <div className="text-[14px] leading-tight text-corp-muted">{b.desc}</div>
            <button
              type="button"
              className="jsp-btn-primary w-full"
              disabled={liveSv < b.cost || busy !== null}
              onClick={() => onBuy(path, b.name)}
            >
              {busy === path ? "…" : "AUTHORIZE"}&nbsp;
              <span className="inline-flex items-center gap-1">
                <CurrencyIcon id="sv" scale={2} />
                {fmt(b.cost)}
              </span>
            </button>
          </div>
        );
      })}
    </section>
  );
}

function MerchPanel({
  data,
  busy,
  onBuy,
}: {
  data: GameView;
  busy: string | null;
  onBuy: (path: string, label: string) => void;
}) {
  return (
    <section className="jsp-card p-3 space-y-2">
      <h2 className="text-corp-accent">CORPORATE MERCH STORE</h2>
      <p className="text-sm text-corp-muted leading-tight">
        Décor for your floors. Paid in Clout (interviews) and Golden Handshakes (offers) — the only
        currencies HR cannot claw back.
      </p>
      <div className="grid grid-cols-1 gap-2">
        {data.cosmetics.map((c) => {
          const sp = COSMETIC_SPRITES[c.id];
          const path = `cosmetics/${c.id}`;
          const afford = Object.entries(c.price).every(
            ([cur, n]) => (data.balances[cur as "clout" | "handshakes"] ?? 0) >= (n ?? 0),
          );
          return (
            <div key={c.id} className="flex items-center gap-2 border-2 border-corp-border p-2">
              <div className="w-12 flex justify-center">
                {sp ? <Sprite map={sp.map} palette={sp.palette} scale={2} /> : null}
              </div>
              <div className="flex-1 min-w-0 leading-tight">
                <div className="text-[15px]">{c.name}</div>
                <div className="text-[13px] text-corp-muted">
                  for {c.floor === "roof" ? "the roof" : data.floors.find((f) => f.id === c.floor)?.name ?? c.floor}
                </div>
              </div>
              {c.owned ? (
                <span className="px-head text-[8px] text-corp-ok">OWNED</span>
              ) : (
                <button
                  type="button"
                  className="jsp-btn-ghost"
                  disabled={!afford || busy !== null}
                  onClick={() => onBuy(path, c.name)}
                >
                  {busy === path ? (
                    "…"
                  ) : (
                    <span className="inline-flex items-center gap-1">
                      {Object.entries(c.price).map(([cur, n]) => (
                        <span key={cur} className="inline-flex items-center gap-1">
                          <CurrencyIcon id={cur} scale={2} />
                          {n}
                        </span>
                      ))}
                    </span>
                  )}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function MemoFeed({ data }: { data: GameView }) {
  return (
    <section className="jsp-card p-3 space-y-1">
      <h2 className="text-corp-accent">PAYROLL MEMOS</h2>
      {data.recent.length === 0 ? (
        <p className="text-sm text-corp-muted leading-tight">
          No payroll activity yet. Review a listing or file an application — the Tower is hungry.
        </p>
      ) : (
        <ul className="space-y-1">
          {data.recent.map((r, i) => (
            <li key={i} className="flex items-start gap-2 text-[15px] leading-tight">
              <CurrencyIcon id={r.currency} scale={2} />
              <span className="flex-1 min-w-0">
                <span className="text-corp-ok">+{r.amount}</span>{" "}
                <span className="text-corp-muted">{REASON_MEMO[r.reason] ?? r.reason}:</span>{" "}
                {r.note ?? ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
