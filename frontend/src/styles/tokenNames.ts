// SPDX-License-Identifier: Apache-2.0
/** The token names and contrast floors that tokens.test.ts enforces and the specimen shows. */

/** Every colour token the slices use; both themes declare each one. */
export const COLOURS = [
  "ground", "surface", "surface-2", "surface-hover", "surface-pressed", "ink", "muted", "line", "line-strong",
  "line-control", "edge", "accent", "accent-hover", "accent-pressed", "accent-ink", "accent-soft", "on-accent",
  "focus", "focus-rail", "warn-bg", "warn-line", "warn-ink", "danger", "danger-hover", "danger-pressed", "danger-bg", "on-danger", "ok",
  "ok-bg", "live", "live-hover", "live-pressed", "live-bg", "on-live", "sim", "sim-bg", "sim-hatch", "brand", "rail",
  "rail-ink", "rail-ink-strong", "rail-dim", "rail-active", "rail-line", "disabled-ink", "disabled-bg",
  "disabled-line", "overlay",
];

type Look = { fg: string; bg: string; border: string };
export type ButtonVariant = "primary" | "secondary" | "simulate" | "live-outline" | "live" | "danger-outline" | "danger";
export const BUTTON_STATE_NAMES = ["default", "hover", "pressed"] as const;

/** Each button variant's text, background and border per state. The Button component and the specimen draw from
 * this, and every combination joins PAIRS, so no rendered state escapes the contrast floors. */
export const BUTTON_STATES: Record<ButtonVariant, Record<(typeof BUTTON_STATE_NAMES)[number], Look>> = {
  primary: {
    default: { fg: "on-accent", bg: "accent", border: "accent" },
    hover: { fg: "on-accent", bg: "accent-hover", border: "accent-hover" },
    pressed: { fg: "on-accent", bg: "accent-pressed", border: "accent-pressed" },
  },
  secondary: {
    default: { fg: "ink", bg: "surface", border: "line-strong" },
    hover: { fg: "ink", bg: "surface-hover", border: "line-strong" },
    pressed: { fg: "ink", bg: "surface-pressed", border: "line-strong" },
  },
  simulate: {
    default: { fg: "sim", bg: "surface", border: "sim" },
    hover: { fg: "sim", bg: "sim-bg", border: "sim" },
    pressed: { fg: "sim", bg: "surface-pressed", border: "sim" },
  },
  "live-outline": {
    default: { fg: "live", bg: "surface", border: "live" },
    hover: { fg: "live", bg: "live-bg", border: "live" },
    pressed: { fg: "live-hover", bg: "surface-pressed", border: "live" }, // live on surface-pressed is 4.43:1
  },
  live: {
    default: { fg: "on-live", bg: "live", border: "live" },
    hover: { fg: "on-live", bg: "live-hover", border: "live-hover" },
    pressed: { fg: "on-live", bg: "live-pressed", border: "live-pressed" },
  },
  "danger-outline": {
    default: { fg: "danger", bg: "surface", border: "danger" },
    hover: { fg: "danger", bg: "danger-bg", border: "danger" },
    pressed: { fg: "danger", bg: "surface-pressed", border: "danger" },
  },
  danger: {
    default: { fg: "on-danger", bg: "danger", border: "danger" },
    hover: { fg: "on-danger", bg: "danger-hover", border: "danger-hover" },
    pressed: { fg: "on-danger", bg: "danger-pressed", border: "danger-pressed" },
  },
};

const BUTTON_PAIRS = Object.values(BUTTON_STATES).flatMap((states) =>
  BUTTON_STATE_NAMES.map((s): [string, string, number] => [states[s].fg, states[s].bg, 4.5]),
);

/** [foreground, background, minimum]: text 4.5:1 (WCAG 1.4.3), boundaries and graphics 3:1 (1.4.11). */
export const PAIRS: [string, string, number][] = ([
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
  // Text the specimen renders elsewhere: the error callout's body, a hovered rail item, a simulated node's text.
  ["ink", "danger-bg", 4.5], ["rail-ink", "rail-line", 4.5], ["muted", "accent-soft", 4.5], // a highlighted menu item's detail
  ["ink", "sim-bg", 4.5], ["muted", "sim-bg", 4.5], ["accent-ink", "sim-bg", 4.5],
  ...BUTTON_PAIRS,
] as [string, string, number][]).filter(([fg, bg], i, all) => all.findIndex(([f, b]) => f === fg && b === bg) === i);
