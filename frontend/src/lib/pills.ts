// SPDX-License-Identifier: Apache-2.0
// Text with data pills (4c-2b): a text field's value as the editor shows it, its text and the references between it
// (engine/graph/values.py's `template`), and a reference's path as a pill names it. Pure functions: the drawer's
// controls draw them, the editor writes what they make.
import { ENVELOPE, fixedOf, kindOf, literal } from "./config";
import { isObject } from "./schemaForm";

/** A reference written in text: its path, and the text it reads as when its value is missing or null. */
export interface Pill {
  ref: string;
  default?: string | null; // a template part's `default`: absent, there's none
}

/** A text field's value as text and pills: n pills between n + 1 texts, each possibly empty. */
export interface Segments {
  texts: string[];
  pills: Pill[];
}

/** Where the caret is: in which text, and how far into it. */
export interface Caret {
  segment: number;
  offset: number;
}

const EMPTY: Segments = { texts: [""], pills: [] };

const bodyOf = (value: unknown): Record<string, unknown> =>
  isObject(value) && isObject(value[ENVELOPE]) ? value[ENVELOPE] : {};

/** A part's `default` as a pill keeps it: text or null; any other value isn't one this editor writes. */
const defaultOf = (part: Record<string, unknown>): Pick<Pill, "default"> | null => {
  if (!("default" in part)) return {};
  const d = part.default;
  return typeof d === "string" || d === null ? { default: d } : null;
};

/** The value as text and pills, or null when it's neither (a formula, a number, an object, an envelope the editor
 * can't read, a template part it doesn't know): the field then shows it some other way. */
export function segmentsOf(value: unknown): Segments | null {
  if (value === undefined || value === null) return EMPTY;
  const kind = kindOf(value);
  if (kind === null || kind === "literal") {
    const fixed = fixedOf(value);
    return typeof fixed === "string" ? { texts: [fixed], pills: [] } : null;
  }
  const body = bodyOf(value);
  if (kind === "ref") {
    const ref = body.path;
    const d = defaultOf(body);
    return typeof ref === "string" && d !== null ? { texts: ["", ""], pills: [{ ref, ...d }] } : null;
  }
  if (kind !== "template" || !Array.isArray(body.parts)) return null;
  const texts = [""];
  const pills: Pill[] = [];
  for (const part of body.parts as unknown[]) {
    if (!isObject(part)) return null;
    if (typeof part.text === "string" && !("ref" in part)) {
      texts[texts.length - 1] += part.text;
      continue;
    }
    const d = defaultOf(part);
    if (typeof part.ref !== "string" || d === null || "text" in part) return null;
    pills.push({ ref: part.ref, ...d });
    texts.push("");
  }
  return { texts, pills };
}

/** What the draft holds for text and pills: nothing, when it's empty; the text, when there are no pills (a literal's
 * payload written back as one); else a template, its empty texts left out. A lone pill is a template too: text, as
 * the field takes it, never the value it reads (which may not be text). */
export function valueOf(s: Segments, asLiteral: boolean, literalOk = true): unknown {
  if (s.pills.length === 0) {
    const text = s.texts.join("");
    if (text === "") return undefined;
    // Where the engine takes no fixed value, text alone is a template of one text part (x-dewpoint-kinds).
    if (!literalOk) return { [ENVELOPE]: { kind: "template", parts: [{ text }] } };
    return asLiteral ? literal(text) : text;
  }
  const parts: Record<string, unknown>[] = [];
  s.texts.forEach((text, i) => {
    if (text !== "") parts.push({ text });
    const pill = s.pills[i];
    if (pill) parts.push("default" in pill ? { ref: pill.ref, default: pill.default } : { ref: pill.ref });
  });
  return { [ENVELOPE]: { kind: "template", parts } };
}

/** Whether two values show the same text and pills: what's written only when a person changes it. */
export function sameSegments(a: Segments, b: Segments): boolean {
  return (
    a.texts.length === b.texts.length &&
    a.texts.every((t, i) => t === b.texts[i]) &&
    a.pills.every((p, i) => {
      const q = b.pills[i]!;
      return p.ref === q.ref && "default" in p === "default" in q && p.default === q.default;
    })
  );
}

/** The text with a pill put at the caret: its text split there. */
export function insertPill(s: Segments, at: Caret, pill: Pill): Segments {
  const text = s.texts[at.segment] ?? "";
  const offset = Math.max(0, Math.min(at.offset, text.length));
  return {
    texts: [...s.texts.slice(0, at.segment), text.slice(0, offset), text.slice(offset), ...s.texts.slice(at.segment + 1)],
    pills: [...s.pills.slice(0, at.segment), pill, ...s.pills.slice(at.segment)],
  };
}

/** The text without its `index`th pill, the texts either side joined, and where the caret goes: where it was. */
export function removePill(s: Segments, index: number): { segments: Segments; caret: Caret } {
  const before = s.texts[index] ?? "";
  const after = s.texts[index + 1] ?? "";
  return {
    segments: {
      texts: [...s.texts.slice(0, index), before + after, ...s.texts.slice(index + 2)],
      pills: [...s.pills.slice(0, index), ...s.pills.slice(index + 1)],
    },
    caret: { segment: index, offset: before.length },
  };
}

/** The pill `index` reading `def` when its value is missing or null; undefined takes its default away. */
export function withDefault(s: Segments, index: number, def: string | null | undefined): Segments {
  const pills = s.pills.map((p, i) => {
    if (i !== index) return p;
    return def === undefined ? { ref: p.ref } : { ref: p.ref, default: def };
  });
  return { texts: s.texts, pills };
}

/** The pill `index` reading another path: its default kept, as what to say when that one is missing. */
export const replacePill = (s: Segments, index: number, ref: string): Segments => ({
  texts: s.texts,
  pills: s.pills.map((p, i) => (i === index ? { ...p, ref } : p)),
});

/** The text with a text changed. */
export const withText = (s: Segments, segment: number, text: string): Segments => ({
  texts: s.texts.map((t, i) => (i === segment ? text : t)),
  pills: s.pills,
});

/** Text and pills as a person reads them back (the recovery file, the list of edits not applied): each pill in braces,
 * as the read-only view writes a template (config.ts's referenceText). */
export const segmentsText = (s: Segments): string =>
  s.texts.map((t, i) => (s.pills[i] ? `${t}{${s.pills[i].ref}}` : t)).join("");

// A reference's path: a root, then fields and indexes (engine/graph/values.py's reference grammar: a field is a name,
// `[A-Za-z_][A-Za-z0-9_]*`; an index is `[n]`).
export type PathPart = { field: string } | { index: number };

const NAME = /^[A-Za-z_][A-Za-z0-9_]*/;

/** The parts of a path (its root first, as a field), or null when it isn't one. */
export function parsePath(path: string): PathPart[] | null {
  const parts: PathPart[] = [];
  let rest = path;
  let first = true;
  while (rest !== "") {
    if (rest.startsWith("[")) {
      const m = /^\[(0|[1-9][0-9]*)\]/.exec(rest);
      if (!m || first) return null;
      parts.push({ index: Number(m[1]) });
      rest = rest.slice(m[0].length);
    } else {
      if (!first) {
        if (!rest.startsWith(".")) return null;
        rest = rest.slice(1);
      }
      const m = NAME.exec(rest);
      if (!m) return null;
      parts.push({ field: m[0] });
      rest = rest.slice(m[0].length);
    }
    first = false;
  }
  return parts.length > 0 ? parts : null;
}

const partText = (parts: PathPart[]): string =>
  parts.map((p, i) => ("index" in p ? `[${p.index}]` : i === 0 ? p.field : `.${p.field}`)).join("");

/** Where a path starts, as a pill says it, and what it reads below: `steps.get_site.output.name` is get_site's name;
 * a loop's `item` or `index` is its loop's; every other root (trigger, vars, item, index, run) is its own. */
export function headOf(path: string): { head: string; rest: string } {
  const parts = parsePath(path);
  if (!parts) return { head: path, rest: "" };
  const field = (i: number) => {
    const p = parts[i];
    return p && "field" in p ? p.field : null;
  };
  let used = 1;
  let head = field(0) ?? path;
  if (head === "steps" && field(1) !== null) {
    head = field(1)!;
    used = field(2) === "output" ? 3 : 2; // a step's output is what it gives: its error is said
  } else if (head === "loops" && field(1) !== null) {
    head = field(1)!;
    used = 2;
  }
  const rest = parts.slice(used);
  return { head, rest: partText(rest) };
}

/** A pill's visible text: `get_site › name`, `trigger › events[0].ap_name`, `run › now`; a root alone is its name. */
export function pillText(path: string): string {
  const { head, rest } = headOf(path);
  return rest === "" ? head : `${head} › ${rest}`;
}
