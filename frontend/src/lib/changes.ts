// SPDX-License-Identifier: Apache-2.0
// An update's changes and a create's settings, as rows (4f-2, the Mist step design §5.3–§5.9): what the config says
// (its `body`'s settings, the names in its `clear`) and what the drawer remembers until it closes (a setting added with
// nothing given yet, a value set before it was cleared, an update's kind). Each change is one write of the whole
// config: one step of Undo, `body` and `clear` together. Nothing here draws.
import { fixedOf, kindOf as envelopeOf, referenceText } from "./config";
import { isObject, type FieldSpec } from "./schemaForm";

/** What a setting's row does: Set (in the body), Clear (named in `clear`), Set with nothing given yet (remembered
 * only), or both set and cleared (a draft from elsewhere: Mist refuses it). */
export type RowState = "set" | "clear" | "pending" | "both";
export interface Row {
  name: string;
  spec: FieldSpec;
  state: RowState;
}

/** What the drawer remembers of the changes until it closes (the tabs unmount what they hide). */
export interface Memory {
  cleared: Record<string, unknown>; // a value set before its setting was cleared: Set brings it back
  pending: string[]; // settings added, nothing given yet
  shown: Record<string, string[]>; // an object's parts added, nothing given yet, by the object's pointer
  entries: Record<string, string[]>; // a map's entries opened, nothing given yet, by the map's pointer
  kind: string | null; // an update's kind, chosen here
  open: string | null; // the object whose own settings' list is open ("＋ Another setting of …")
  adding: { pointer: string; parts: string[] } | null; // a map's new entry: its key first, then these parts
}
export const NO_MEMORY: Memory = { cleared: {}, pending: [], shown: {}, entries: {}, kind: null, open: null, adding: null };

/** `names` added to what `pointer`'s object shows, each once. */
export const showing = (shown: Memory["shown"], pointer: string, names: string[]): Memory["shown"] => ({
  ...shown,
  [pointer]: [...new Set([...(shown[pointer] ?? []), ...names])],
});

type Config = Record<string, unknown>;

/** The body's settings, when it's a plain object the list can draw (not a formula, a reference or a literal). */
export function bodyObject(config: Config): Record<string, unknown> | null {
  const body = config.body;
  if (body === undefined) return {};
  return isObject(body) && envelopeOf(body) === null ? body : null;
}

/** The names `clear` holds, when it's a plain list of names. */
export function clearNames(config: Config): string[] | null {
  const clear = config.clear;
  if (clear === undefined) return [];
  return Array.isArray(clear) && clear.every((n): n is string => typeof n === "string") ? clear : null;
}

/** A row per setting given, cleared or added, of the ones the schema describes; `first` (a create's required
 * settings, given or not) in their order, then the others by title. */
export function rowsOf(specs: FieldSpec[], body: Record<string, unknown>, clear: string[], pending: string[], first: string[] = []): Row[] {
  const names = new Set([...Object.keys(body), ...clear, ...pending, ...first]);
  const rank = (name: string) => (first.includes(name) ? first.indexOf(name) : first.length);
  return specs
    .filter((s) => names.has(s.name))
    .map((spec): Row => {
      const set = spec.name in body;
      const cleared = clear.includes(spec.name);
      return { name: spec.name, spec, state: set && cleared ? "both" : set ? "set" : cleared ? "clear" : "pending" };
    })
    .sort((a, b) => rank(a.name) - rank(b.name) || a.spec.label.localeCompare(b.spec.label) || a.name.localeCompare(b.name));
}

const withClear = (config: Config, names: string[]): Config => {
  const rest = Object.fromEntries(Object.entries(config).filter(([k]) => k !== "clear"));
  return names.length > 0 ? { ...rest, clear: names } : rest;
};
const withBody = (config: Config, body: Record<string, unknown>): Config => ({ ...config, body });
const without = (body: Record<string, unknown>, name: string) => Object.fromEntries(Object.entries(body).filter(([k]) => k !== name));

// A body or a `clear` held as a formula, a reference or a literal is never written into: it stays as it is (the final
// review; ledger 102).

/** Set: in the body (with `value`, when one is given), out of `clear`. */
export function setIn(config: Config, name: string, value: unknown): Config {
  const body = bodyObject(config);
  if (body === null) return config;
  const next = withBody(config, value === undefined ? body : { ...body, [name]: value });
  const names = clearNames(config);
  return names === null ? next : withClear(next, names.filter((n) => n !== name));
}

/** Clear: out of the body, named in `clear`. */
export function clearIn(config: Config, name: string): Config {
  const names = clearNames(config);
  if (names === null) return config;
  const body = bodyObject(config);
  const next = body === null ? config : withBody(config, without(body, name));
  return withClear(next, names.includes(name) ? names : [...names, name]);
}

/** Keep: neither set nor cleared. */
export function keepIn(config: Config, name: string): Config {
  const body = bodyObject(config);
  const next = body === null ? config : withBody(config, without(body, name));
  const names = clearNames(config);
  return names === null ? next : withClear(next, names.filter((n) => n !== name));
}

/** How many settings change: set with a value, or cleared. */
export const changedCount = (rows: Row[]): number => rows.filter((r) => r.state !== "pending").length;

/** The branch an update's body is, by its kind's value when the draft holds it, else the one chosen here, else the
 * first that has every setting listed, else the first. A create's, only by its kind's value. */
export function kindIndex(
  widget: "update" | "create", body: Record<string, unknown>, listed: string[], kind: { name: string; values: string[] },
  offered: string[][], chosen: string | null,
): number | null {  // prettier-ignore
  const held = kind.values.indexOf(String(fixedOf(body[kind.name])));
  if (held >= 0) return held;
  if (widget === "create") return null;
  // The one chosen here, while it has every setting listed: an Undo can bring back one it lacks.
  const picked = chosen === null ? -1 : kind.values.indexOf(chosen);
  if (picked >= 0 && listed.every((n) => offered[picked]!.includes(n))) return picked;
  const fits = offered.findIndex((names) => listed.every((n) => names.includes(n)));
  return fits >= 0 ? fits : 0;
}

/** Another kind: the changes it has too are kept, the others dropped (what no kind offers stays: the list doesn't draw
 * it); the kind's value written where it's held (a draft that has it, a create's). `known`: what any kind offers
 * (all listed, when not given). */
export function kindIn(
  config: Config, kind: { name: string; values: string[] }, to: number, offered: string[], write: boolean, known?: string[],
): { config: Config; kept: string[]; dropped: string[] } {  // prettier-ignore
  const body = bodyObject(config);
  const clear = clearNames(config);
  const isKnown = (n: string) => known === undefined || known.includes(n);
  const stays = (n: string) => offered.includes(n) || !isKnown(n);
  const listed = [...new Set([...Object.keys(body ?? {}).filter((n) => n !== kind.name), ...(clear ?? [])])].filter(isKnown);
  const kept = listed.filter((n) => offered.includes(n));
  const dropped = listed.filter((n) => !offered.includes(n));
  let next = config;
  if (body !== null) {
    const kept = Object.fromEntries(Object.entries(body).filter(([k]) => k === kind.name || stays(k)));
    next = withBody(next, write ? { ...kept, [kind.name]: kind.values[to] } : kept);
  }
  if (clear !== null) next = withClear(next, clear.filter(stays));
  return { config: next, kept, dropped };
}

const joinedWords = (words: string[]): string =>
  words.length <= 1 ? (words[0] ?? "") : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;

/** The changes' words (§5.3–§5.9). */
export const WORDS = {
  merge: "Merge with the current settings",
  replace: "Replace them",
  mergeSays: "Merge reads the current settings when the step runs and keeps the parts of each setting below that you don't give. A change made in Mist in between may be overwritten.",
  replaceSays: "Replace sends each setting below as written: the parts you don't give go back to Mist's defaults. Settings not listed stay as they are.",
  partsMerge: "Its parts left empty stay as they are: merge changes only those given.",
  partsReplace: "Its parts left empty go back to Mist's defaults: replace sends it as written.",
  wholeList: "A list is sent whole: it replaces the current one, and an item's parts left empty go back to Mist's defaults.",
  cleared: "Sent empty: Mist removes this setting.",
  pending: "Nothing given yet: it isn't sent.",
  both: "Both set and cleared: Mist refuses this when it runs. Choose Set or Clear.",
  nothing: "Nothing to change yet: add a setting to set, or one to clear. An update that changes nothing fails when it runs.",
  json: "As JSON: Mist takes it in more than one shape.",
  changesOnSetup: "The changes are on Setup.",
  settingsOnSetup: "The settings are on Setup.",
  formulaUpdate: "Computed when the step runs: the settings it gives are set; with merge, the parts it leaves out stay as they are.",
  formulaCreate: "Computed when the step runs: the settings it gives are sent; Mist uses its defaults for the others.",
  chooseKind: "Choose the kind first: its settings follow.",
  count: (widget: "update" | "create", n: number, of: number) =>
    widget === "update"
      ? `${n} of ${of} settings change; the others stay as they are.`
      : `${n} of ${of} settings given; Mist uses its defaults for the others.`,
  kindChanged: (title: string, kept: string[], dropped: string[]) =>
    dropped.length === 0
      ? `Kind changed to ${title}: every change is kept.`
      : kept.length === 0
        ? `Kind changed to ${title}: ${joinedWords(dropped)} ${dropped.length === 1 ? "is" : "are"} dropped, as a ${title} doesn't have ${dropped.length === 1 ? "it" : "them"}.`
        : `Kind changed to ${title}: ${joinedWords(kept)} ${kept.length === 1 ? "is" : "are"} kept; ${joinedWords(dropped)} ${dropped.length === 1 ? "is" : "are"} dropped, as a ${title} doesn't have ${dropped.length === 1 ? "it" : "them"}.`,
};

/** A value in a few words, for a read-only summary: yes or no, the text, a value's source, a part's count. */
export function brief(spec: FieldSpec | undefined, value: unknown): string {
  if (spec?.sensitive) return "a sensitive value";
  const kind = envelopeOf(value);
  if (kind === "ref" || kind === "template") return referenceText(value);
  if (kind === "cel") return "computed when the step runs";
  const fixed = fixedOf(value);
  if (typeof fixed === "boolean") return fixed ? "yes" : "no";
  if (typeof fixed === "string" || typeof fixed === "number") return String(fixed);
  if (Array.isArray(fixed)) return fixed.length === 1 ? "1 item" : `${fixed.length} items`;
  if (isObject(fixed)) return Object.keys(fixed).length === 1 ? "1 setting" : `${Object.keys(fixed).length} settings`;
  return "empty";
}

/** What a read-only view says of the changes (§5.9): how they're sent and how many, then a line per setting. */
export function summaryOf(
  widget: "update" | "create", rows: Row[], body: Record<string, unknown>, mode: unknown, partsOf: (spec: FieldSpec) => FieldSpec[],
): { head: string; lines: { name: string; label: string; text: string }[] } {  // prettier-ignore
  const n = changedCount(rows);
  const head =
    widget === "update"
      ? `${fixedOf(mode) === "replace" ? WORDS.replace : WORDS.merge} · ${n === 1 ? "1 change" : `${n} changes`}`
      : `${n === 1 ? "1 setting" : `${n} settings`} given`;
  const lines = rows
    .filter((r) => r.state !== "pending")
    .map((r) => {
      if (r.state === "clear") return { name: r.name, label: r.spec.label, text: "cleared" };
      const value = fixedOf(body[r.name]);
      const parts = r.spec.base === "group" && isObject(value) && envelopeOf(value) === null ? partsOf(r.spec) : null;
      const said = parts
        ? Object.entries(value as Record<string, unknown>)
            .map(([k, v]) => {
              const part = parts.find((p) => p.name === k);
              return `${part?.label ?? k} ${brief(part, v)}`;
            })
            .join(", ")
        : brief(r.spec, body[r.name]);
      return { name: r.name, label: r.spec.label, text: `${r.state === "both" ? "set and cleared" : "set"}: ${said}` };
    });
  return { head, lines };
}
