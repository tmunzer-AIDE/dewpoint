// SPDX-License-Identifier: Apache-2.0
/** The token names and contrast floors that tokens.test.ts enforces and the specimen shows. */

/** Every colour token the slices use; both themes declare each one. */
export const COLOURS = [
  "ground", "surface", "surface-2", "surface-hover", "surface-pressed", "ink", "muted", "line", "line-strong",
  "line-control", "edge", "accent", "accent-hover", "accent-pressed", "accent-ink", "accent-soft", "on-accent",
  "focus", "focus-rail", "warn-bg", "warn-line", "warn-ink", "danger", "danger-hover", "danger-bg", "on-danger", "ok",
  "ok-bg", "live", "live-hover", "live-pressed", "live-bg", "on-live", "sim", "sim-bg", "sim-hatch", "brand", "rail",
  "rail-ink", "rail-ink-strong", "rail-dim", "rail-active", "rail-line", "disabled-ink", "disabled-bg",
  "disabled-line", "overlay",
];

/** [foreground, background, minimum]: text 4.5:1 (WCAG 1.4.3), boundaries and graphics 3:1 (1.4.11). */
export const PAIRS: [string, string, number][] = [
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
  ["sim", "surface", 4.5], ["sim", "sim-bg", 4.5], ["sim", "sim-hatch", 4.5], // simulated text crosses the hatch
  ["edge", "ground", 3], ["edge", "surface", 3],
  ["rail-ink", "rail", 4.5], ["rail-dim", "rail", 4.5], ["rail-ink-strong", "rail-active", 4.5], ["focus-rail", "rail", 3],
  ["brand", "rail", 3],
];
