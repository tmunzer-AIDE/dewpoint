// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import main from "../main.tsx?raw";
import app from "./app.css?raw";
import css from "./tokens.css?raw";

/** The declarations of the first rule whose selector is exactly `selector`, with `var()` references resolved. */
function block(selector: string): Map<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no rule for ${selector}`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  const out = new Map<string, string>();
  for (const m of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) out.set(m[1]!, m[2]!.trim());
  const resolve = (v: string, depth = 0): string =>
    depth > 5 ? v : v.replace(/var\((--[a-z0-9-]+)\)/g, (_, name: string) => resolve(out.get(name) ?? `?${name}`, depth + 1));
  for (const [k, v] of out) out.set(k, resolve(v));
  return out;
}

type Rgba = [number, number, number, number];

function parse(value: string): Rgba {
  const hex = /^#([0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const n = parseInt(hex[1]!, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
  }
  const rgba = /^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/.exec(value);
  if (rgba) return [Number(rgba[1]), Number(rgba[2]), Number(rgba[3]), Number(rgba[4])];
  throw new Error(`not a colour: ${value}`);
}

/** `top` composited over the opaque `base`. */
function over(top: Rgba, base: Rgba): Rgba {
  const a = top[3];
  return [top[0] * a + base[0] * (1 - a), top[1] * a + base[1] * (1 - a), top[2] * a + base[2] * (1 - a), 1];
}

function luminance([r, g, b]: Rgba): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(a: Rgba, b: Rgba): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const LIGHT = ':root, [data-theme="light"]';
const DARK = '[data-theme="dark"]';
const DARK_BY_OS = ':root:not([data-theme="light"])';

const COLOURS = [
  "ground", "surface", "surface-2", "surface-hover", "surface-pressed", "ink", "muted", "line", "line-strong",
  "line-control", "edge", "accent", "accent-hover", "accent-pressed", "accent-ink", "accent-soft", "on-accent", "focus",
  "focus-rail", "warn-bg", "warn-line", "warn-ink", "danger", "danger-hover", "danger-bg", "on-danger", "ok", "ok-bg",
  "live", "live-hover", "live-pressed", "live-bg", "on-live", "sim", "sim-bg", "sim-hatch", "brand", "rail", "rail-ink",
  "rail-dim", "rail-active", "rail-line", "disabled-ink", "disabled-bg", "disabled-line", "overlay",
];

/** [foreground, background, minimum]: text 4.5:1 (WCAG 1.4.3), boundaries and graphics 3:1 (1.4.11). */
const PAIRS: [string, string, number][] = [
  ...["ground", "surface", "surface-2", "surface-hover", "surface-pressed"].flatMap(
    (bg): [string, string, number][] => [["ink", bg, 4.5], ["muted", bg, 4.5], ["line-control", bg, 3], ["focus", bg, 3]],
  ),
  ["accent-ink", "surface", 4.5], ["accent-ink", "ground", 4.5], ["accent-ink", "accent-soft", 4.5],
  ["focus", "accent-soft", 3],
  ["on-accent", "accent", 4.5], ["on-accent", "accent-hover", 4.5], ["on-accent", "accent-pressed", 4.5],
  ["warn-ink", "warn-bg", 4.5], ["warn-ink", "surface", 4.5],
  ["danger", "surface", 4.5], ["danger", "danger-bg", 4.5], ["on-danger", "danger", 4.5], ["on-danger", "danger-hover", 4.5],
  ["ok", "surface", 4.5], ["ok", "ok-bg", 4.5],
  ["live", "surface", 4.5], ["live", "live-bg", 4.5],
  ["on-live", "live", 4.5], ["on-live", "live-hover", 4.5], ["on-live", "live-pressed", 4.5],
  ["sim", "surface", 4.5], ["sim", "sim-bg", 4.5],
  ["edge", "ground", 3], ["edge", "surface", 3],
  ["rail-ink", "rail", 4.5], ["rail-dim", "rail", 4.5], ["rail-ink", "rail-active", 4.5], ["focus-rail", "rail", 3],
  ["brand", "rail", 3],
];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme tokens", (_, selector) => {
  const tokens = block(selector);
  const colour = (name: string, base?: Rgba): Rgba => {
    const value = tokens.get(`--${name}`);
    if (value === undefined) throw new Error(`--${name} is missing`);
    const c = parse(value);
    return c[3] < 1 ? over(c, base ?? parse(tokens.get("--rail")!)) : c;
  };

  it("declares every colour the slices use", () => {
    expect(COLOURS.filter((n) => !tokens.has(`--${n}`))).toEqual([]);
  });

  it.each(PAIRS)("%s on %s reaches %s:1", (fg, bg, min) => {
    const back = colour(bg);
    expect(ratio(colour(fg, back), back)).toBeGreaterThanOrEqual(min);
  });
});

describe("theme switching", () => {
  it("gives the OS dark preference exactly the explicit dark theme", () => {
    expect([...block(DARK_BY_OS)]).toEqual([...block(DARK)]);
  });
});

describe("type and shape (D7, outline §6)", () => {
  const base = block(":root");

  it("uses the design's three families", () => {
    expect(base.get("--font-sans")).toMatch(/^"Instrument Sans"/);
    expect(base.get("--font-display")).toMatch(/^"Schibsted Grotesk"/);
    expect(base.get("--font-mono")).toMatch(/^"JetBrains Mono"/);
  });

  it("keeps radii at 8 px, dialogs at 12 px, and the pill shape for data pills only", () => {
    const radii = [...base].filter(([k]) => k.startsWith("--radius"));
    expect(radii.length).toBeGreaterThan(0);
    for (const [name, value] of radii) {
      const px = parseFloat(value);
      if (name === "--radius-pill") expect(px).toBe(999);
      else if (name === "--radius-dialog") expect(px).toBe(12);
      else expect(px).toBeLessThanOrEqual(8);
    }
  });
});

describe("the bundle's fonts (D7)", () => {
  const imports = [...main.matchAll(/import "(@fontsource\/[^"]+)";/g)].map((m) => m[1]);

  it("loads only the design's families, Latin subsets only", () => {
    expect(imports.length).toBeGreaterThan(0);
    for (const i of imports) expect(i).toMatch(/^@fontsource\/(instrument-sans|schibsted-grotesk|jetbrains-mono)\/latin-\d00\.css$/);
  });

  it("loads every weight the tokens use", () => {
    expect(imports).toEqual(
      expect.arrayContaining([
        "@fontsource/instrument-sans/latin-400.css",
        "@fontsource/instrument-sans/latin-500.css",
        "@fontsource/instrument-sans/latin-600.css",
        "@fontsource/schibsted-grotesk/latin-600.css",
        "@fontsource/jetbrains-mono/latin-400.css",
        "@fontsource/jetbrains-mono/latin-500.css",
        "@fontsource/jetbrains-mono/latin-600.css",
      ]),
    );
  });
});

describe("the Tailwind theme (app.css)", () => {
  const theme = app.slice(app.indexOf("@theme"), app.indexOf("}", app.indexOf("@theme")));
  const base = block(":root");

  it("keeps test sources out of the class scan, so fixtures never become utilities", () => {
    for (const glob of ["../**/*.test.ts", "../**/*.test.tsx", "../test"]) expect(app).toContain(`@source not "${glob}";`);
  });

  it("exposes every colour token as a utility", () => {
    expect(COLOURS.filter((n) => !theme.includes(`--color-${n}: var(--${n});`))).toEqual([]);
  });

  it("exposes the type, radius and shadow tokens", () => {
    const names = [...base.keys()].filter((k) => /^--(type|radius)/.test(k));
    const wanted = [
      ...names.map((k) => (k.startsWith("--type-") ? `--text-${k.slice(7)}: var(${k});` : `${k}: var(${k});`)),
      "--shadow-node: var(--shadow-node);",
      "--shadow-dialog: var(--shadow-dialog);",
      "--font-display: var(--font-display);",
    ];
    expect(wanted.filter((w) => !theme.includes(w))).toEqual([]);
  });
});

