// SPDX-License-Identifier: Apache-2.0
// A workflow's CSV file (4c-3b; the mockups' InputCsv and InputEdit boards; engine 2b spec §8.1): `settings.csv`, its
// typed columns and its limits. A draft is saved only when its graph's format takes it (engine/graph/model.py's
// CsvSettings and CsvColumn, strict), so nothing here writes a declaration the save would refuse (D19): that is
// `csvProblem`. Every other rule (unique headers and names, a required column's default) is the server's to say.
// Columns are written through `setAt`, so a list edited in place keeps its lineage and a removal starts a new one: a
// held edit inside a column is applied only to the column it was typed in (ruling 113).
import type { Schemas } from "./client";
import { DECIMAL, setAt } from "./config";
import { isObject } from "./schemaForm";
import type { GraphDoc } from "./workflows";

export type CsvColumn = Schemas["CsvColumn"];
export type CsvSettings = Schemas["CsvSettings"];
export type CsvType = CsvColumn["type"];

export const CSV_TYPES: { value: CsvType; label: string }[] = [
  { value: "string", label: "Text" },
  { value: "integer", label: "Whole number" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Yes or no" },
  { value: "mac", label: "MAC address" },
  { value: "ip", label: "IP address" },
  { value: "cidr", label: "Network (CIDR)" },
  { value: "enum", label: "Choice" },
];
export const typeLabel = (t: string) => CSV_TYPES.find((x) => x.value === t)?.label ?? t;

// engine/graph/model.py and engine/graph/csv.py: what a draft's CSV declaration may be.
export const MAX_COLUMNS = 200;
export const MAX_ROWS = 10_000;
export const MAX_BYTES = 5 * 1024 * 1024;
const MAX_HEADER = 200;
const MAX_NAME = 63;
const MAX_VALUES = 200;
const MAX_VALUE = 200;
const COLUMN_KEYS = new Set(["header", "name", "type", "required", "default", "sensitive", "values"]);
const TYPES = new Set<string>(CSV_TYPES.map((t) => t.value));

const sized = (v: unknown, max: number) => typeof v === "string" && v.length >= 1 && v.length <= max;
const count = (v: unknown, max: number) => typeof v === "number" && Number.isInteger(v) && v >= 1 && v <= max;

/** Why a draft's save would refuse this as `settings.csv`, or null: the strict model's own bounds, in words. */
export function csvProblem(csv: unknown): string | null {
  if (csv === undefined) return null;
  if (!isObject(csv) || Object.keys(csv).some((k) => !["columns", "max_rows", "max_bytes"].includes(k))) {
    return "A CSV file's declaration holds its columns and, optionally, its most rows and its largest file.";
  }
  if (!Array.isArray(csv.columns) || csv.columns.length < 1 || csv.columns.length > MAX_COLUMNS) {
    return `A CSV file has from 1 to ${MAX_COLUMNS} columns.`;
  }
  for (const [i, c] of (csv.columns as unknown[]).entries()) {
    const n = i + 1;
    if (!isObject(c) || Object.keys(c).some((k) => !COLUMN_KEYS.has(k))) return `Column ${n} holds something a column can't.`;
    if (!sized(c.header, MAX_HEADER)) return `Column ${n}'s header is from 1 to ${MAX_HEADER} characters.`;
    if (!sized(c.name, MAX_NAME)) return `Column ${n}'s name is from 1 to ${MAX_NAME} characters.`;
    if (typeof c.type !== "string" || !TYPES.has(c.type)) return `Column ${n}'s type is one of: ${CSV_TYPES.map((t) => t.value).join(", ")}.`;
    if (("required" in c && typeof c.required !== "boolean") || ("sensitive" in c && typeof c.sensitive !== "boolean")) {
      return `Column ${n}'s required and sensitive are true or false.`;
    }
    const values = c.values;
    if (values !== undefined && values !== null) {
      if (!Array.isArray(values) || values.length > MAX_VALUES || !values.every((v) => typeof v === "string" && v.length <= MAX_VALUE)) {
        return `Column ${n}'s values are at most ${MAX_VALUES} texts of at most ${MAX_VALUE} characters.`;
      }
    }
  }
  if (csv.max_rows !== undefined && !count(csv.max_rows, MAX_ROWS)) return `Most rows is a whole number from 1 to ${MAX_ROWS.toLocaleString("en-US")}.`;
  if (csv.max_bytes !== undefined && !count(csv.max_bytes, MAX_BYTES)) return "The largest file is from 1 byte to 5 MB.";
  return null;
}

export const csvOf = (doc: GraphDoc): CsvSettings | null => (isObject(doc.settings?.csv) ? (doc.settings.csv) : null);

/** A column whose header and name no other column has: "Column 3", `column_3`. */
function freshColumn(columns: CsvColumn[]): CsvColumn {
  let n = columns.length + 1;
  while (columns.some((c) => c.header === `Column ${n}` || c.name === `column_${n}`)) n++;
  return { header: `Column ${n}`, name: `column_${n}`, type: "string" };
}

/** A new CSV file of one text column: a declaration has one at least. */
export const newCsv = (): CsvSettings => ({ columns: [freshColumn([])] });

export const addColumn = (csv: CsvSettings): CsvSettings => setAt(csv, ["columns", csv.columns.length], freshColumn(csv.columns)) as CsvSettings;

/** The declaration without column `i`; null for its last one: a declaration keeps one, and the file goes instead. */
export const removeColumn = (csv: CsvSettings, i: number): CsvSettings | null =>
  csv.columns.length <= 1 ? null : (setAt(csv, ["columns", i], undefined) as CsvSettings);

/** Whether a default still fits a column after its type or values changed. */
function fits(c: CsvColumn, v: unknown): boolean {
  switch (c.type) {
    case "integer":
      return typeof v === "number" && Number.isInteger(v);
    case "number":
      return typeof v === "number";
    case "boolean":
      return typeof v === "boolean";
    case "enum":
      return typeof v === "string" && (c.values ?? []).includes(v);
    default:
      return typeof v === "string";
  }
}

/** The declaration with column `i` changed as `patch` says, each key written in place: only a Choice has values, a
 * sensitive column has no default, and a default its new type or values don't fit goes. Undefined removes a key. */
export function setColumn(csv: CsvSettings, i: number, patch: Partial<CsvColumn>): CsvSettings {
  const was = csv.columns[i];
  if (!was) return csv;
  const next: CsvColumn = { ...was, ...patch };
  const writes: [string, unknown][] = Object.entries(patch);
  if (next.type !== "enum" && "values" in was) writes.push(["values", undefined]);
  if (next.type === "enum" && !Array.isArray(next.values)) writes.push(["values", []]);
  if ("default" in next && (next.sensitive === true || !fits({ ...next, values: next.type === "enum" ? (next.values ?? []) : null }, next.default))) {
    writes.push(["default", undefined]);
  }
  let out: unknown = csv;
  for (const [key, value] of writes) out = setAt(out, ["columns", i, key], value);
  return out as CsvSettings;
}

/** The declaration with its limits: undefined leaves one to the platform's. */
export const setLimits = (csv: CsvSettings, limits: { max_rows?: number; max_bytes?: number }): CsvSettings =>
  Object.entries(limits).reduce((out: unknown, [k, v]) => setAt(out, [k], v), csv) as CsvSettings;

/** A column's rules, in its row: "required, default 0", "sensitive", "default HQ". */
export function rulesOf(c: CsvColumn): string {
  const shown = (v: unknown) => (typeof v === "boolean" ? (v ? "yes" : "no") : String(v));
  return [c.required ? "required" : null, c.sensitive ? "sensitive" : null, "default" in c ? `default ${shown(c.default)}` : null]
    .filter((p) => p !== null)
    .join(", ");
}

/** The largest file as typed, in MB, as bytes: up to the platform's 5 MB. Null when it isn't a size, or isn't decimal
 * (#73). */
export function bytesOf(mb: string): number | null {
  const n = DECIMAL.test(mb.trim()) ? Number(mb.trim()) : NaN;
  if (mb.trim() === "" || !Number.isFinite(n) || n <= 0) return null;
  const bytes = Math.round(n * 1024 * 1024);
  return bytes >= 1 && bytes <= MAX_BYTES ? bytes : null;
}

/** Bytes as the form shows them, in MB, without a trailing zero: 5242880 is "5". */
export const mbOf = (bytes: number) => String(Number((bytes / 1024 / 1024).toFixed(3)));

type Limit = { value: number | undefined } | { problem: string };

/** Most rows as typed: empty leaves it to the platform's 10,000. */
export function rowsLimit(text: string): Limit {
  const t = text.trim();
  if (t === "") return { value: undefined };
  const n = /^\d{1,6}$/.test(t) ? Number(t) : NaN;
  return n >= 1 && n <= MAX_ROWS ? { value: n } : { problem: `A whole number from 1 to ${MAX_ROWS.toLocaleString("en-US")}.` };
}

/** The largest file as typed, in MB: empty leaves it to the platform's 5 MB. */
export function sizeLimit(text: string): Limit {
  if (text.trim() === "") return { value: undefined };
  const bytes = bytesOf(text);
  return bytes === null ? { problem: "A size in MB, above 0 and up to 5." } : { value: bytes };
}

/** Why a column's header or name as typed wouldn't be saved, or null: from 1 to 200, and 1 to 63, characters. */
export function textProblem(key: "header" | "name", text: string): string | null {
  const max = key === "header" ? MAX_HEADER : MAX_NAME;
  return text.length >= 1 && text.length <= max ? null : `${key === "header" ? "A header" : "A name"} is from 1 to ${max} characters.`;
}
