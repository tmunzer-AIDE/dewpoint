// SPDX-License-Identifier: Apache-2.0
// The condition builder's formulas (4c-2b; the owner's rulings: per-comparison guards, "is there" and "is missing"
// defined, one level of groups; ledger rulings 119 and M65). A condition is comparisons, each a path the scope gives
// with the guards it needs (as data), joined by all or any, with groups one level deep. Written as CEL that is false,
// never an error, on any data: each comparison is its guards, its null test, a test of its value's type where the
// operator would fail on another, and the comparison. Read back only when it's what the builder wrote: the formula
// written again from what's read is the same text, or it stays a formula ("the builder opens only what it wrote").
import type { Guard } from "./data";

export type Op =
  | "is" | "is_not" | "contains" | "starts_with" | "ends_with" | "more" | "less" | "at_least" | "at_most"
  | "is_true" | "is_false" | "is_empty" | "is_not_empty" | "is_there" | "is_missing";  // prettier-ignore

export const OP_WORDS: Record<Op, string> = {
  is: "is", is_not: "is not", contains: "contains", starts_with: "starts with", ends_with: "ends with",
  more: "is more than", less: "is less than", at_least: "is at least", at_most: "is at most", is_true: "is true",
  is_false: "is false", is_empty: "is empty", is_not_empty: "is not empty", is_there: "is there", is_missing: "is missing",
};  // prettier-ignore

/** A value compared with: text, or a number as typed (checked: valueProblem). */
export type Literal = { kind: "text"; text: string } | { kind: "number"; text: string };

export interface Row {
  path: string;
  op: Op;
  value: Literal | null; // null for operators that take none
  guards: Guard[];
  nullTest: boolean; // "is there" includes `path != null` (the scope's null_test)
}

export interface Group {
  match: "all" | "any";
  rows: Row[];
}

export interface Condition {
  match: "all" | "any";
  items: (Row | Group)[];
}

export const isGroup = (x: Row | Group): x is Group => "rows" in x;

const TEXT_OPS: Op[] = ["contains", "starts_with", "ends_with"];
const NUMBER_OPS: Op[] = ["more", "less", "at_least", "at_most"];
export const NO_VALUE: ReadonlySet<Op> = new Set(["is_true", "is_false", "is_empty", "is_not_empty", "is_there", "is_missing"]);

/** The operators a value of these types takes (R6 §4.3): a date and time is compared as written, never ordered (its
 * text can't be ordered, and its parse fails on many values); "is there" only where something may be missing, so an
 * object that's always there takes none (the review of revision 1). */
export function opsFor(types: readonly string[], format: string | null, mayBeMissing: boolean): Op[] {
  const t = types.filter((x) => x !== "null");
  const presence: Op[] = mayBeMissing ? ["is_there", "is_missing"] : [];
  if (types.length === 0 || t.length > 1) {
    return ["is", "is_not", ...TEXT_OPS, ...NUMBER_OPS, "is_true", "is_false", ...presence];
  }
  switch (t[0]) {
    case "string":
      return format === "date-time" ? ["is", "is_not", ...presence] : ["is", "is_not", ...TEXT_OPS, ...presence];
    case "integer":
    case "number":
      return ["is", "is_not", ...NUMBER_OPS, ...presence];
    case "boolean":
      return ["is_true", "is_false", ...presence];
    case "array":
      return ["is_empty", "is_not_empty", ...presence];
    default:
      return presence; // an object, or what's only null
  }
}

/** Whether "is" and "is not" compare with a number: the value is only ever one. */
export const numeric = (types: readonly string[]): boolean => {
  const t = types.filter((x) => x !== "null");
  return t.length > 0 && t.every((x) => x === "integer" || x === "number");
};

const JSON_NUMBER = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$/;
const INT64 = { min: -(2n ** 63n), max: 2n ** 63n - 1n };
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** Why a value can't be compared with, or null. A number is written as typed, JSON's way, finite and, whole, within
 * CEL's int; the loop's `index` takes whole numbers only (CEL types it int). Text with a lone surrogate isn't text CEL
 * reads. */
export function valueProblem(value: Literal, path: string): string | null {
  if (value.kind === "text") return LONE_SURROGATE.test(value.text) ? "This text holds a character that can't be written." : null;
  const t = value.text.trim();
  if (!JSON_NUMBER.test(t)) return "Write a number, like 3, -2 or 0.5.";
  if (!Number.isFinite(Number(t))) return "This number is too large.";
  const whole = !/[.eE]/.test(t);
  if (whole && (BigInt(t) < INT64.min || BigInt(t) > INT64.max)) return "This whole number is too large.";
  if (path === "index" && !whole) return "The loop's position is a whole number.";
  return null;
}

const literalCel = (v: Literal): string => (v.kind === "text" ? JSON.stringify(v.text) : v.text.trim());

/** A guard as CEL, a type tested by a value's type: a type's name fails every run (ledger M65). */
export function guardCel(g: Guard): string {
  switch (g.kind) {
    case "present":
      return `has(${g.path})`;
    case "not_null":
      return `${g.path} != null`;
    case "is_map":
      return `type(${g.path}) == type({})`;
    case "is_list":
      return `type(${g.path}) == type([])`;
    default:
      return `size(${g.path}) > ${g.size ?? 0}`;
  }
}

/** "is there" (ruling 119): its guards, and not null where the scope says. Empty when it always is. */
export const thereOf = (r: Pick<Row, "path" | "guards" | "nullTest">): string[] => [
  ...r.guards.map(guardCel),
  ...(r.nullTest ? [`${r.path} != null`] : []),
];

/** The test of a value's own presence: `has()` of a field, the size that holds an item; null for a root. */
function presenceOf(path: string): string | null {
  const item = /^(.*)\[(0|[1-9][0-9]*)\]$/.exec(path);
  if (item) return `size(${item[1]}) > ${item[2]}`;
  return path.includes(".") ? `has(${path})` : null;
}

/** "is there" as written: its tests end with one of the value itself, so the formula names the value it tests, even
 * where only an ancestor's guards decide it (an item's field that's always there; the review of revision 1). */
function presenceCel(r: Row): string {
  const there = thereOf(r);
  const own = r.nullTest ? `${r.path} != null` : presenceOf(r.path);
  return (own === null || there.at(-1) === own ? there : [...there, own]).join(" && ") || "true";
}

const NUMBER_TEST = (p: string) => `(type(${p}) == type(0) || type(${p}) == type(0.0))`;
const ORDER: Partial<Record<Op, string>> = { more: ">", less: "<", at_least: ">=", at_most: "<=" };
const METHOD: Partial<Record<Op, string>> = { contains: "contains", starts_with: "startsWith", ends_with: "endsWith" };

/** The comparison's own tests, after "is there". */
function testOf(r: Row): string[] {
  const p = r.path;
  const v = r.value ? literalCel(r.value) : "";
  switch (r.op) {
    case "is":
      return [`${p} == ${v}`];
    case "is_not":
      return [`${p} != ${v}`];
    case "contains":
    case "starts_with":
    case "ends_with":
      return [`type(${p}) == type("")`, `${p}.${METHOD[r.op]}(${v})`];
    case "more":
    case "less":
    case "at_least":
    case "at_most":
      return [NUMBER_TEST(p), `${p} ${ORDER[r.op]} ${v}`];
    case "is_true":
      return [`${p} == true`];
    case "is_false":
      return [`${p} == false`];
    case "is_empty":
      return [`type(${p}) == type([])`, `size(${p}) == 0`];
    case "is_not_empty": // `!= 0`: `size(x) > n` is an item being there, its presence's own test (the review of revision 2)
      return [`type(${p}) == type([])`, `size(${p}) != 0`];
    default:
      return [];
  }
}

/** One comparison as CEL, in parentheses: false whenever its data is missing, null or another shape. */
export function rowCel(r: Row): string {
  if (r.op === "is_missing") return `!(${presenceCel(r)})`;
  if (r.op === "is_there") return `(${presenceCel(r)})`;
  return `(${[...thereOf(r), ...testOf(r)].join(" && ")})`;
}

const JOIN = { all: "&&", any: "||" } as const;

/** The formula a condition writes, or undefined when it has no comparison. Each item on its own line. */
export function write(c: Condition): string | undefined {
  const items = c.items.filter((x) => !isGroup(x) || x.rows.length > 0);
  if (items.length === 0) return undefined;
  const text = (x: Row | Group) => (isGroup(x) ? `(${x.rows.map(rowCel).join(` ${JOIN[x.match]} `)})` : rowCel(x));
  return items.map(text).join(`\n${JOIN[c.match]} `);
}

// Reading back. A formula is split where the builder joins (outside parentheses and text), each comparison into its
// tests; what's read must be written again as the same text, or it isn't the builder's.

/** Splits `s` at each top-level `sep`, outside parentheses, brackets, braces and strings. */
function split(s: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let start = 0;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]!;
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (depth === 0 && s.startsWith(sep, i)) {
      out.push(s.slice(start, i));
      start = i + sep.length;
      i += sep.length - 1;
    }
  }
  out.push(s.slice(start));
  return out;
}

/** The text inside one pair of outer parentheses, or null. */
function inner(s: string, open = "("): string | null {
  if (!s.startsWith(open) || !s.endsWith(")")) return null;
  const body = s.slice(open.length, -1);
  return balanced(body) ? body : null;
}

function balanced(s: string): boolean {
  let depth = 0;
  let quote: string | null = null;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]!;
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(") depth++;
    else if (ch === ")" && --depth < 0) return false;
  }
  return depth === 0;
}

const PATH = "([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*|\\[(?:0|[1-9][0-9]*)\\])*)";
const GUARDS: [RegExp, (m: RegExpExecArray) => Guard][] = [
  [new RegExp(`^has\\(${PATH}\\)$`), (m) => ({ kind: "present", path: m[1]!, size: null })],
  [new RegExp(`^${PATH} != null$`), (m) => ({ kind: "not_null", path: m[1]!, size: null })],
  [new RegExp(`^type\\(${PATH}\\) == type\\(\\{\\}\\)$`), (m) => ({ kind: "is_map", path: m[1]!, size: null })],
  [new RegExp(`^type\\(${PATH}\\) == type\\(\\[\\]\\)$`), (m) => ({ kind: "is_list", path: m[1]!, size: null })],
  [new RegExp(`^size\\(${PATH}\\) > (0|[1-9][0-9]*)$`), (m) => ({ kind: "min_size", path: m[1]!, size: Number(m[2]) })],
];

const LIT = '("(?:[^"\\\\]|\\\\.)*"|-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)';
/** A value as the builder writes it, or null: text CEL reads and JSON doesn't (`"\x41"`) isn't the builder's, and a
 * formula holding it stays a formula, never an error (the review of revision 1). */
function literalOf(text: string): Literal | null {
  if (!text.startsWith('"')) return { kind: "number", text };
  try {
    return { kind: "text", text: JSON.parse(text) as string };
  } catch {
    return null;
  }
}

/** The comparison a row's last tests make: its operator, path and value, and how many tests it took. */
function testFrom(tests: string[]): { op: Op; path: string; value: Literal | null; used: number } | null {
  const last = tests.at(-1) ?? "";
  const prev = tests.at(-2) ?? "";
  let m: RegExpExecArray | null;
  if ((m = new RegExp(`^${PATH} == (true|false)$`).exec(last))) return { op: m[2] === "true" ? "is_true" : "is_false", path: m[1]!, value: null, used: 1 };
  if ((m = new RegExp(`^${PATH} (==|!=) ${LIT}$`).exec(last))) {
    const value = literalOf(m[3]!);
    return value && { op: m[2] === "==" ? "is" : "is_not", path: m[1]!, value, used: 1 };
  }
  if ((m = new RegExp(`^${PATH}\\.(contains|startsWith|endsWith)\\(${LIT}\\)$`).exec(last)) && prev === `type(${m[1]}) == type("")`) {
    const op = m[2] === "contains" ? "contains" : m[2] === "startsWith" ? "starts_with" : "ends_with";
    const value = literalOf(m[3]!);
    return value && { op, path: m[1]!, value, used: 2 };
  }
  if ((m = new RegExp(`^${PATH} (>|<|>=|<=) ${LIT}$`).exec(last)) && prev === NUMBER_TEST(m[1]!)) {
    const op = (Object.entries(ORDER).find(([, s]) => s === m![2])?.[0] ?? "more") as Op;
    const value = literalOf(m[3]!);
    return value && { op, path: m[1]!, value, used: 2 };
  }
  if ((m = new RegExp(`^size\\(${PATH}\\) (==|!=) 0$`).exec(last)) && prev === `type(${m[1]}) == type([])`) {
    return { op: m[2] === "==" ? "is_empty" : "is_not_empty", path: m[1]!, value: null, used: 2 };
  }
  return null;
}

/** A row from its tests, the guards first: null when they aren't the builder's. */
function rowFrom(tests: string[], presence: "is_there" | "is_missing" | null): Row | null {
  let path: string | null = null;
  let op: Op;
  let value: Literal | null = null;
  let rest = tests;
  if (presence) {
    op = presence;
  } else {
    const t = testFrom(tests);
    if (!t) return null;
    ({ op, path, value } = t);
    rest = tests.slice(0, tests.length - t.used);
  }
  const guards: Guard[] = [];
  let nullTest = false;
  for (const text of rest) {
    const hit = GUARDS.map(([re, make]) => {
      const m = re.exec(text);
      return m ? make(m) : null;
    }).find((g) => g !== null);
    if (!hit) return null;
    // The last `path != null` is the null test of its own path, when it reads that path.
    if (hit.kind === "not_null" && (path === null ? text === rest.at(-1) : hit.path === path)) {
      nullTest = true;
      path ??= hit.path;
    } else guards.push(hit);
  }
  if (path === null) {
    // "is there" with no null test: the value its last test names, a field's `has()` or an item's size.
    const last = guards.at(-1);
    path = last?.kind === "present" ? last.path : last?.kind === "min_size" ? `${last.path}[${last.size}]` : null;
  }
  return path === null ? null : { path, op, value, guards, nullTest };
}

function itemFrom(text: string): Row | Group | null {
  if (text.startsWith("!(")) {
    const body = inner(text, "!(");
    return body === null ? null : rowFrom(body === "true" ? [] : split(body, " && "), "is_missing");
  }
  const body = inner(text);
  if (body === null) return null;
  const ors = split(body, " || ");
  const ands = split(body, " && ");
  // A group of one: its comparison, in parentheses of its own. Its match says nothing until a second one joins.
  if (ors.length === 1 && ands.length === 1 && (body.startsWith("(") || body.startsWith("!("))) {
    const only = itemFrom(body);
    if (only !== null && !isGroup(only)) return { match: "any", rows: [only] };
  }
  // A group is comparisons in parentheses, each itself in parentheses.
  for (const [parts, match] of [[ors, "any"], [ands, "all"]] as const) {
    if (parts.length > 1 && parts.every((p) => p.startsWith("(") || p.startsWith("!("))) {
      const rows = parts.map((p) => itemFrom(p));
      if (rows.every((r): r is Row => r !== null && !isGroup(r))) return { match, rows };
    }
  }
  return rowFrom(ands, null) ?? rowFrom(ands, "is_there");
}

/** The condition a formula is, when the builder wrote it (written again, it's the same text); null otherwise. */
export function read(formula: string): Condition | null {
  for (const match of ["all", "any"] as const) {
    const parts = split(formula, `\n${JOIN[match]} `);
    const items = parts.map(itemFrom);
    if (items.some((x) => x === null)) continue;
    const c: Condition = { match, items: items as (Row | Group)[] };
    if (write(c) === formula) return c;
  }
  return null;
}
