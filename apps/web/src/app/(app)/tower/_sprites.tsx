// Pixel sprites for The Tower, drawn from character grids so every
// building, drone and poster is code (no image assets). Each grid row is
// one pixel row; "." is transparent; other characters index the palette.

import type { CSSProperties } from "react";

export type Palette = Record<string, string>;

export function Sprite({
  map,
  palette,
  scale = 3,
  className,
  style,
  title,
}: {
  map: string[];
  palette: Palette;
  scale?: number;
  className?: string;
  style?: CSSProperties;
  title?: string;
}) {
  const h = map.length;
  const w = Math.max(...map.map((r) => r.length));
  const rects: JSX.Element[] = [];
  map.forEach((row, y) => {
    // Merge horizontal runs of the same colour into one rect.
    let x = 0;
    while (x < row.length) {
      const ch = row[x];
      if (ch === "." || !palette[ch]) {
        x++;
        continue;
      }
      let run = 1;
      while (x + run < row.length && row[x + run] === ch) run++;
      rects.push(<rect key={`${x}-${y}`} x={x} y={y} width={run} height={1} fill={palette[ch]} />);
      x += run;
    }
  });
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width={w * scale}
      height={h * scale}
      shapeRendering="crispEdges"
      className={className}
      style={style}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      {title ? <title>{title}</title> : null}
      {rects}
    </svg>
  );
}

// --- Characters ---------------------------------------------------------------

export const WORKER = [
  "..hhhh..",
  ".hhhhhh.",
  ".hseseh.",
  "..ssss..",
  "...ss...",
  ".ttwktt.",
  "t.twkt.t",
  "s.ttkt.s",
  "..tttt..",
  "..pp.pp.",
  "..pp.pp.",
  ".bb..bb.",
];
export const workerPalette = (suit: string, hair: string, tie = "#c0392b"): Palette => ({
  h: hair, s: "#f1c27d", e: "#1b1b1b", t: suit, w: "#eeeeee", k: tie, p: "#2b2b3a", b: "#111111",
});

// --- Fixtures (free, per floor theme) ------------------------------------------

export const DESK = [
  "....mmmmmm....",
  "....mccccm....",
  "....mccccm....",
  "....mmmmmm....",
  "......mm......",
  "wwwwwwwwwwwwww",
  "w............w",
  "w............w",
];
export const CABINET = [
  "gggggggg",
  "gddddddg",
  "gdhhhhdg",
  "gddddddg",
  "gggggggg",
  "gddddddg",
  "gdhhhhdg",
  "gddddddg",
  "gggggggg",
  "g......g",
];
export const CRATE = [
  "bbbbbbbb",
  "bkkkkkkb",
  "bkbkkbkb",
  "bkkbbkkb",
  "bkbkkbkb",
  "bkkkkkkb",
  "bbbbbbbb",
];
export const LAMP = [
  ".pp.",
  "pmmp",
  "pmMp",
  "pMmp",
  "pmmp",
  "pmMp",
  ".pp.",
  ".gg.",
  "gggg",
];
export const SERVER = [
  "rrrrrrrr",
  "rdddddar",
  "rdddddbr",
  "rrrrrrrr",
  "rdddddar",
  "rdddddar",
  "rrrrrrrr",
  "rdddddbr",
  "rdddddar",
  "rrrrrrrr",
  "rdddddar",
  "rdddddbr",
  "rrrrrrrr",
  "r......r",
];
export const TABLE = [
  "wwwwwwwwwwwwwwwwwwwwwwww",
  "WWWWWWWWWWWWWWWWWWWWWWWW",
  ".w....................w.",
  ".w....................w.",
  ".w....................w.",
];
export const WINDOW = [
  "ffffffffffffffff",
  "fssssssssssssssf",
  "fsssssyssssssssf",
  "fsssssssssssyssf",
  "fsbbssssbbssssbf",
  "fsbbssbbbbsbbsbf",
  "fbbbbsbbbbbbbsbf",
  "fbbbbbbbbbbbbbbf",
  "ffffffffffffffff",
];
export const PAMPHLETS = [
  "aaaaaa",
  "awwwwa",
  "apppwa",
  "aaaaaa",
  "awwwwa",
  "awpppa",
  "aaaaaa",
  "a....a",
];

// --- Cosmetics -------------------------------------------------------------------

export const POSTER = [
  "ffffffffff",
  "fyyyyyyyyf",
  "fyyyycyyyf",
  "fyyyccyyyf",
  "fyyycccyyf",
  "fyyyyyyyyf",
  "fykkkkkkyf",
  "fyyyyyyyyf",
  "fykkkkkyyf",
  "fyyyyyyyyf",
  "ffffffffff",
];
export const FICUS = [
  "...gg...",
  "..gGgg..",
  ".gggGgg.",
  "..gGgg..",
  ".ggggGg.",
  "..gggg..",
  "...bb...",
  "..pppp..",
  "..pppp..",
  "...pp...",
];
export const COOLER = [
  ".bbbb.",
  "bwwwwb",
  "bwwwwb",
  ".bbbb.",
  "gggggg",
  "gggggg",
  "ggrrgg",
  "gggggg",
  "gggggg",
  "g....g",
];
export const PLAQUE = [
  "yyyyyyyy",
  "yddddddy",
  "yddyyddy",
  "ydyyyydy",
  "yddyyddy",
  "yddddddy",
  "ydwwwwdy",
  "yyyyyyyy",
];
export const STAPLER = [
  "...yyyyyyy",
  "..yYYYYYYy",
  ".yyyyyyyyy",
  "dddddddddd",
];
export const AQUARIUM = [
  "ffffffffffff",
  "fwwwwwwwwwwf",
  "fwwwwwwwowwf",
  "fwwwwwwooowf",
  "fwwwwwwwowwf",
  "fwgwwwwwwwwf",
  "fwggwwwwwgwf",
  "fssssssssssf",
  "ffffffffffff",
];
export const HELIPAD = [
  "...cccccccccccccc...",
  "..c..y........y..c..",
  "..c..yyyyyyyyyy..c..",
  "..c..y........y..c..",
  "...cccccccccccccc...",
];
export const ANTENNA = [
  "..r..",
  "..g..",
  "..g..",
  ".ggg.",
  "ggggg",
];

export const COSMETIC_SPRITES: Record<string, { map: string[]; palette: Palette }> = {
  poster: { map: POSTER, palette: { f: "#5a3e1b", y: "#f4d35e", c: "#e07a5f", k: "#3d405b" } },
  ficus: { map: FICUS, palette: { g: "#2d6a4f", G: "#52b788", b: "#6b4226", p: "#b5651d" } },
  cooler: { map: COOLER, palette: { b: "#4ea8de", w: "#caf0f8", g: "#adb5bd", r: "#d00000" } },
  plaque: { map: PLAQUE, palette: { y: "#e9c46a", d: "#3a2e1f", w: "#f8f9fa" } },
  stapler: { map: STAPLER, palette: { y: "#ffd700", Y: "#fff3a0", d: "#5c4400" } },
  aquarium: { map: AQUARIUM, palette: { f: "#2b2d42", w: "#48cae4", o: "#f77f00", g: "#2d6a4f", s: "#e9c46a" } },
  helipad: { map: HELIPAD, palette: { c: "#f8f9fa", y: "#ffd60a" } },
};

// --- Currency icons ---------------------------------------------------------------

export const ICONS: Record<string, { map: string[]; palette: Palette }> = {
  scrip: {
    map: [".wwwwww.", ".wkkkkw.", ".wwwwww.", ".wkkkww.", ".wwwwww.", ".wkkkkw.", ".wwwwww.", "........"],
    palette: { w: "#f1faee", k: "#457b9d" },
  },
  chits: {
    map: ["..rrrr..", ".rrrrrr.", "rrwrrwrr", "rrrwwrrr", "rrrwwrrr", "rrwrrwrr", ".rrrrrr.", "..rrrr.."],
    palette: { r: "#e63946", w: "#f1faee" },
  },
  sv: {
    map: ["...gg...", "..gggg..", ".gggggg.", "...gg...", "yyyyyyyy", "yYYyyYYy", "yyyyyyyy", "........"],
    palette: { g: "#60e474", y: "#ffcc40", Y: "#fff1a8" },
  },
  clout: {
    map: ["...yy...", "...yy...", "yyyyyyyy", ".yyyyyy.", "..yyyy..", ".yy..yy.", "yy....yy", "........"],
    palette: { y: "#c77dff" },
  },
  handshakes: {
    map: ["..yyyy..", ".yyyyyy.", "yydyydyy", "yydddddy", "yydyydyy", ".yyyyyy.", "..yyyy..", "........"],
    palette: { y: "#ffd700", d: "#7a5c00" },
  },
};

export function CurrencyIcon({ id, scale = 2 }: { id: string; scale?: number }) {
  const icon = ICONS[id];
  if (!icon) return null;
  return <Sprite map={icon.map} palette={icon.palette} scale={scale} />;
}
