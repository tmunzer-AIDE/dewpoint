// SPDX-License-Identifier: Apache-2.0
// A step test's values (4d-1c; the simulation design §7.6, D-s2; the TestTab and TestOther boards): what the step's
// seed contract allows for each (a value; null where its read is nullable; absent where it's optional), where a value
// comes from (its step's own sample, as the server decided) or why it's typed, its title, and the values sent. Text is
// sent as typed; anything else is read as JSON, as the draft's values are. An empty value is a value not given.
import { idKey, nodesOf } from "../../../lib/graph";
import { parseJson } from "../../../lib/config";
import type { SeedContract, SeedEntry } from "../../../lib/simulations";
import type { GraphDoc, NodeType } from "../../../lib/workflows";
import { regionOf } from "./loopBody";

export type Choice = "value" | "null" | "absent";
/** A value as the form holds it: what's chosen (null: nothing yet) and what's typed. */
export interface SeedInput {
  choice: Choice | null;
  text: string;
}
/** The values to send, or each value's problem: those missing apart from those that don't read. */
export type Collected = { values: Record<string, unknown>; absent: string[] } | { missing: string[]; problems: Record<string, string> };

export function choicesOf(e: SeedEntry): Choice[] {
  if (e.required) return e.nullable ? ["value", "null"] : ["value"];
  return e.nullable ? ["value", "null", "absent"] : ["value", "absent"];
}

const WORDS: Record<string, string> = {
  string: "text", integer: "whole number", number: "number", boolean: "true or false", object: "object", array: "list",
};  // prettier-ignore
export function typeWords(types: string[]): string {
  const said = types.filter((t) => t !== "null").map((t) => WORDS[t] ?? t);
  return said.length > 0 ? said.join(" or ") : "any value";
}

/** Typed as text (sent as typed), or as JSON. */
export const isText = (e: SeedEntry) => e.types.length > 0 && e.types.every((t) => t === "string" || t === "null");
const textOf = (e: SeedEntry, v: unknown) => (isText(e) && typeof v === "string" ? v : JSON.stringify(v, null, 2));

export function initialOf(e: SeedEntry): SeedInput {
  if (e.prefill.state === "prefilled") return { choice: "value", text: textOf(e, e.prefill.value) };
  return { choice: choicesOf(e).length === 1 ? "value" : null, text: "" };
}

/** The prefill's text, while the value is still the sample's. */
export const prefilled = (e: SeedEntry): string | null => (e.prefill.state === "prefilled" ? textOf(e, e.prefill.value) : null);

const segments = (pointer: string) => pointer.split("/").slice(1).map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));

/** Where a value comes from, or why it's typed (D-s2's reasons), and what null and absent mean for it. */
export function hintOf(e: SeedEntry): string {
  const [root, step] = segments(e.pointer);
  const owner = root === "steps" ? step : "its step";
  let from = "";
  if (e.prefill.state === "prefilled") from = `From ${owner}'s sample.`;
  else if (e.prefill.reason === "sensitive") from = "Sensitive: typed, never prefilled. Kept as a protected value.";
  else if (e.prefill.reason === "no_sample") from = `Typed: ${owner} has no sample yet.`;
  else if (e.prefill.reason === "not_faithful") from = `Typed: ${owner}'s sample was cut or redacted, so it isn't used.`;
  else if (e.prefill.reason === "not_in_sample") from = `Typed: ${owner}'s sample doesn't hold this value.`;
  else if (e.prefill.reason === "doesnt_fit") from = `Typed: ${owner}'s sample doesn't fit what this step reads.`;
  else if (e.prefill.reason === "not_step_output") {
    from =
      root === "vars" ? "Typed: variables have no sample."
      : root === "item" || root === "index" ? "Typed: a loop's item has no sample."
      : root === "trigger" ? "Typed: the workflow's input has no sample."
      : "Typed: only a step's output has a sample.";  // prettier-ignore
  }
  const nulls =
    e.required && e.nullable ? "It can be null, but it can't be left out."
    : !e.required && e.nullable ? "Null and absent differ: a default replaces both, but has() is true for null."
    : "";  // prettier-ignore
  return [from, nulls].filter(Boolean).join(" ");
}

/** A schema's title at a path of property names, else null. */
function titleIn(schema: unknown, path: string[]): string | null {
  let at: unknown = schema;
  for (const p of path) {
    const props = (at as { properties?: Record<string, unknown> } | undefined)?.properties;
    at = props?.[p] ?? (/^\d+$/.test(p) ? (at as { items?: unknown } | undefined)?.items : undefined);
    if (at === undefined) return null;
  }
  const title = (at as { title?: unknown } | undefined)?.title;
  return typeof title === "string" ? title : null;
}

/** A value's title: its schema's (the workflow's input, a step's output) where it has one, a loop's item by its loop,
 * else its last name. `stepId`: the step tested, whose loop an item is. */
export function titleOf(pointer: string, doc: GraphDoc, types: Map<string, NodeType>, stepId: string): string {
  const [root, ...rest] = segments(pointer);
  const last = rest.at(-1) ?? root ?? pointer;
  if (root === "trigger") return titleIn(doc.settings?.input_schema, rest) ?? last;
  if (root === "steps" && rest[1] === "output") {
    const step = nodesOf(doc).find((n) => n.key === rest[0]);
    if (rest.length === 2) return `${rest[0]}'s output`;
    return titleIn(step ? types.get(step.type)?.output_schema : undefined, rest.slice(2)) ?? last;
  }
  if ((root === "item" || root === "index") && rest.length === 0) {
    const loops = nodesOf(doc).filter((n) => n.type.startsWith("flow.loop@")).map((n) => ({ n, region: regionOf(doc, n.id) }));
    const mine = loops.filter((l) => l.region.has(idKey(stepId))).sort((a, b) => a.region.size - b.region.size)[0];
    return mine ? `${mine.n.key}'s ${root}` : root;
  }
  return last;
}

/** The values to send, or what's missing on each and what doesn't read, sending nothing. */
export function collect(contract: SeedContract, inputs: Record<string, SeedInput>, stepKey: string): Collected {
  const values: Record<string, unknown> = {};
  const absent: string[] = [];
  const problems: Record<string, string> = {};
  const missing: string[] = [];
  for (const e of contract.entries) {
    const input = inputs[e.pointer] ?? initialOf(e);
    const choice = input.choice ?? (choicesOf(e).length === 1 ? "value" : null);
    if (choice === "null") values[e.pointer] = null;
    else if (choice === "absent") absent.push(e.pointer);
    else if (choice === null || input.text === "") {
      missing.push(e.pointer);
      problems[e.pointer] =
        e.required && !e.nullable ? `Give a value: ${stepKey} reads it without a default.`
        : e.required ? "Give a value, or choose Null."
        : "Give a value, or choose Absent.";  // prettier-ignore
    } else if (isText(e)) values[e.pointer] = input.text;
    else {
      const read = parseJson(input.text);
      if ("problem" in read) problems[e.pointer] = read.problem.replace("isn't saved", "isn't sent");
      else values[e.pointer] = read.value;
    }
  }
  return Object.keys(problems).length > 0 ? { missing, problems } : { values, absent };
}
