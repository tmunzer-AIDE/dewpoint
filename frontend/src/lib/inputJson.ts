// SPDX-License-Identifier: Apache-2.0
// The input as JSON (4c-3b; the InputEdit board's "Edit as JSON"): `settings.input_schema` and `settings.csv` as one
// text, saved with the draft as it's typed when it reads as JSON a save takes; text that doesn't stays held, with the
// line where it breaks (ruling 113). The server's problems name a pointer (`/settings/csv/columns/1/default`): each is
// shown at the line its value starts on.
import { parseJson } from "./config";
import { csvOf, csvProblem, type CsvSettings } from "./csv";
import { formOrdered, inputOf, orderAsWritten } from "./input";
import { isObject, type Schema } from "./schemaForm";
import type { GraphDoc } from "./workflows";

export interface InputDocument {
  input_schema: Schema;
  csv?: CsvSettings;
}

/** The draft's input as the JSON text shows it: its fields in the form's order, its CSV file only when it declares one. */
export function inputText(doc: GraphDoc): string {
  const csv = csvOf(doc);
  const shown: InputDocument = { input_schema: formOrdered(inputOf(doc)), ...(csv ? { csv } : {}) };
  return JSON.stringify(shown, null, 2);
}

/** The line a parse failed at, from the browser's own message: a line and column, or a position. */
function breakLine(text: string, message: string): number | null {
  const line = /line (\d+)/i.exec(message);
  if (line) return Number(line[1]);
  const at = /position (\d+)/i.exec(message);
  return at ? text.slice(0, Number(at[1])).split("\n").length : null;
}

/** The JSON text as the input it says, or why a save wouldn't take it, with its line when the text breaks. */
export function readInput(text: string): { value: InputDocument } | { problem: string; line: number | null } {
  try {
    JSON.parse(text);
  } catch (e) {
    const line = breakLine(text, e instanceof Error ? e.message : "");
    return { problem: "This isn't valid JSON, so it isn't saved.", line };
  }
  const parsed = parseJson(text);
  if ("problem" in parsed) return { problem: parsed.problem, line: null };
  const v = parsed.value;
  if (!isObject(v) || !isObject(v.input_schema) || Object.keys(v).some((k) => k !== "input_schema" && k !== "csv")) {
    return { problem: "It holds `input_schema`, an object, and optionally `csv`.", line: null };
  }
  const csv = v.csv === null ? undefined : v.csv;
  const problem = csvProblem(csv);
  if (problem) return { problem, line: null };
  return { value: { input_schema: orderAsWritten(v.input_schema), ...(csv ? { csv: csv as CsvSettings } : {}) } };
}

/** A settings pointer as a reader says it: `/settings/csv/columns/1/default` is `csv.columns[1].default`. */
export function pointerWords(pointer: string): string {
  const parts = pointer.replace(/^\/settings\//, "").split("/").map((p) => p.replaceAll("~1", "/").replaceAll("~0", "~"));
  return parts.reduce((out, p, i) => (/^(0|[1-9]\d*)$/.test(p) ? `${out}[${p}]` : i === 0 ? p : `${out}.${p}`), "");
}

const escape = (key: string) => key.replaceAll("~", "~0").replaceAll("/", "~1");

/** Text the line finder can't read as JSON. */
class Malformed extends Error {}

/** The line each value of valid JSON text starts on, by its pointer from the text's root ("" is the root). */
export function pointerLines(text: string): Map<string, number> {
  const lines = new Map<string, number>();
  let i = 0;
  let line = 1;
  // Text that isn't JSON (cut off, a stray token, a bad escape) has no lines: every scan stops at its end and a stray
  // character ends it, so the finder always ends (4c-3b's final review).
  const broken = (): never => {
    throw new Malformed();
  };
  const at = (c: string) => i < text.length && text[i] === c;
  const space = () => {
    while (i < text.length && /\s/.test(text[i]!)) {
      if (text[i] === "\n") line++;
      i++;
    }
  };
  const string = (): string => {
    if (!at('"')) broken();
    const start = i;
    i++;
    while (i < text.length && text[i] !== '"') i += text[i] === "\\" ? 2 : 1;
    if (i >= text.length) broken();
    i++;
    return JSON.parse(text.slice(start, i)) as string;
  };
  const value = (pointer: string): void => {
    space();
    if (i >= text.length) broken();
    lines.set(pointer, line);
    const c = text[i];
    if (c === "{") {
      i++;
      space();
      if (at("}")) return void i++;
      for (;;) {
        space();
        const key = string();
        space();
        if (!at(":")) broken();
        i++;
        value(`${pointer}/${escape(key)}`);
        space();
        if (at("}")) return void i++;
        if (!at(",")) broken();
        i++;
      }
    }
    if (c === "[") {
      i++;
      space();
      if (at("]")) return void i++;
      for (let n = 0; ; n++) {
        value(`${pointer}/${n}`);
        space();
        if (at("]")) return void i++;
        if (!at(",")) broken();
        i++;
      }
    }
    if (c === '"') return void string();
    const scalar = i;
    while (i < text.length && !/[\s,\]}]/.test(text[i]!)) i++;
    if (i === scalar) broken(); // a stray ",", "]" or "}" where a value goes
  };
  try {
    JSON.parse(text); // what isn't JSON (a value or a space JSON doesn't have) has no line, the scan never guessing
    value("");
    space();
    if (i < text.length) broken(); // something after the value
  } catch (e) {
    if (e instanceof Malformed || e instanceof SyntaxError) return new Map();
    throw e;
  }
  return lines;
}

/** Where a settings problem shows in the JSON text: its line, the nearest value the text has on its way down. */
export function lineOf(text: string, pointer: string): number | null {
  const lines = pointerLines(text);
  let at = pointer.replace(/^\/settings/, "");
  for (;;) {
    const found = lines.get(at);
    if (found !== undefined) return found;
    if (at === "") return null;
    at = at.slice(0, at.lastIndexOf("/"));
  }
}
