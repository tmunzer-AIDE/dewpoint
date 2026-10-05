// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import main from "../main.tsx?raw";
import app from "./app.css?raw";
import themeCss from "./theme.css?raw";
import { contrast, over, parseColour, type Rgba } from "./contrast";
import { COLOURS, PAIRS } from "./tokenNames";
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

const LIGHT = ':root, [data-theme="light"]';
const DARK = '[data-theme="dark"]';
const DARK_BY_OS = ':root:not([data-theme="light"])';

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme tokens", (_, selector) => {
  const tokens = block(selector);
  const colour = (name: string, base?: Rgba): Rgba => {
    const value = tokens.get(`--${name}`);
    if (value === undefined) throw new Error(`--${name} is missing`);
    const c = parseColour(value);
    return c[3] < 1 ? over(c, base ?? parseColour(tokens.get("--rail")!)) : c;
  };

  it("declares every colour the slices use", () => {
    expect(COLOURS.filter((n) => !tokens.has(`--${n}`))).toEqual([]);
  });

  it.each(PAIRS)("%s on %s reaches %s:1", (fg, bg, min) => {
    const back = colour(bg);
    expect(contrast(colour(fg, back), back)).toBeGreaterThanOrEqual(min);
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

describe("the Tailwind theme (theme.css, app.css)", () => {
  const theme = themeCss.slice(themeCss.indexOf("@theme"), themeCss.indexOf("}", themeCss.indexOf("@theme")));
  const base = block(":root");

  it("keeps tests and the specimen out of the app's class scan, so neither ships utilities", () => {
    for (const glob of ["../**/*.test.ts", "../**/*.test.tsx", "../test", "../specimen"]) {
      expect(app).toContain(`@source not "${glob}";`);
    }
  });

  it("turns JetBrains Mono's ligatures off, so code shows what was typed (`!=`, never `≠`)", () => {
    expect(themeCss).toMatch(/code,\s*kbd,\s*pre,\s*samp,\s*\.font-mono\s*\{[^}]*font-variant-ligatures:\s*none;/);
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

