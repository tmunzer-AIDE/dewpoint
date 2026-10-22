// SPDX-License-Identifier: Apache-2.0
// A start form's input (4c-3b; shared since 4d-1c): each field of a form as its control, what's typed read back as the
// input's values, and the input entered whole as JSON where the fields can't show its rules. A schedule's form and the
// Simulate workflow dialog both enter an input this way; a sensitive field is never prefilled with what it hides. A
// picker field is a combobox listing its choices, in a form that gives it a route (./pickerField; the 4f-3 design §5.2).
import type { ReactNode } from "react";
import { Field, Select, TextArea } from "../../components/Field";
import { Tag } from "../../components/Tag";
import { parseJson } from "../../lib/config";
import { isObject } from "../../lib/schemaForm";
import type { StartField } from "../../lib/triggers";
import { parseNumber } from "../../lib/unapplied";
import { PickerField, isPicker, usePickerForm } from "./pickerField";

/** How a field of the input is entered: one of its values, as its type says, or JSON for what the simple controls can't
 * hold (a list, an object, several types or none), each value's type kept (the review of revision 1). */
export type Entry = "choice" | "yesno" | "whole" | "number" | "text" | "json";

export function entryOf(f: StartField): Entry {
  if (Array.isArray(f.enum) && !f.enum_masked) return "choice";
  const type: unknown = f.type;
  return type === "boolean" ? "yesno" : type === "integer" ? "whole" : type === "number" ? "number" : type === "string" ? "text" : "json";
}

export const JSON_HINT = 'As JSON, like ["ap-1"] or {"site": "HQ"}; text in quotes.';

export const nameOf = (f: StartField) => f.title ?? f.name;

/** What's typed for one field of the input, as the input holds it: nothing given is left out. A choice's option is its
 * value as JSON, so a number stays a number; JSON a parse would change (a number too large, a whole one past 2^53) is
 * refused, as the draft's is. */
export function valueOf(f: StartField, typed: string | undefined): { value: unknown } | { problem: string } {
  if (typed === undefined || typed === "") return { value: undefined };
  const entry = entryOf(f);
  if (entry === "choice") return { value: JSON.parse(typed) as unknown };
  if (entry === "yesno") return { value: typed === "true" };
  if (entry === "whole" || entry === "number") {
    const parsed = parseNumber(typed, entry === "whole");
    return "problem" in parsed ? parsed : { value: parsed.value };
  }
  if (entry === "text") return { value: typed };
  return parseJson(typed);
}

/** A value as its field's control shows it, or null where that control can't show it as it is: a line break, which a
 * one-line control drops, or text that doesn't read back as the value (an empty text is "not given"). The reviews of
 * revisions 4 and 5. */
export function shownOf(f: StartField, v: unknown): string | null {
  const shown = textOf(f, v);
  if (shown === null || /[\r\n]/.test(shown)) return null;
  const read = valueOf(f, shown);
  return "value" in read && JSON.stringify(read.value) === JSON.stringify(v) ? shown : null;
}

/** A value as its field's control would hold it, before it's read back. */
export function textOf(f: StartField, v: unknown): string | null {
  switch (entryOf(f)) {
    case "choice":
      return (f.enum ?? []).some((x) => JSON.stringify(x) === JSON.stringify(v)) ? JSON.stringify(v) : null;
    case "yesno":
      return typeof v === "boolean" ? String(v) : null;
    case "whole":
      return typeof v === "number" && Number.isInteger(v) ? String(v) : null;
    case "number":
      return typeof v === "number" ? String(v) : null;
    case "text":
      return typeof v === "string" ? v : null;
    case "json":
      return JSON.stringify(v);
  }
}

/** Where a field's problem is kept among the form's: apart from its own (`when`, `input`…), whatever the field's name. */
export const fieldKey = (name: string) => `field:${name}`;

/** The fields' values as one input, each by its name as a key of its own (a field may be named `__proto__`), or each
 * field's problem; `required` holds a required field to being given. */
export function fromFields(
  form: { fields: StartField[] }, values: ReadonlyMap<string, string>, required: boolean,
  requiredWords: (f: StartField) => string = (f) => `${nameOf(f)} is required.`,
): { input: Record<string, unknown> } | { problems: Record<string, string> } {
  const entries: [string, unknown][] = [];
  const problems: [string, string][] = [];
  for (const f of form.fields) {
    const read = valueOf(f, values.get(f.name));
    if ("problem" in read) problems.push([fieldKey(f.name), read.problem]);
    else if (read.value !== undefined) entries.push([f.name, read.value]);
    else if (required && f.required) problems.push([fieldKey(f.name), requiredWords(f)]);
  }
  return problems.length > 0 ? { problems: Object.fromEntries(problems) } : { input: Object.fromEntries(entries) };
}

/** What a required field left empty says (the InputFields board). */
export const REQUIRED = "Give a value: the input requires it.";

/** A field's label, with what it is beside it, and what its hint adds: optional ones are left out when empty, sensitive
 * ones stored as protected values (the InputFields board; the run form's Main board, 4e-2). */
export const labelOf = (f: StartField) => (
  <>
    {nameOf(f)}
    {f.required && <> <Tag>required</Tag></>}
    {f.sensitive && <> <Tag>sensitive</Tag></>}
  </>
);
export const hintOf = (f: StartField) =>
  [
    f.description,
    f.required ? null : "Optional: left out when empty.",
    f.sensitive ? "Stored as a protected value: results show it as redacted." : null,
  ].filter(Boolean).join(" ") || undefined;  // prettier-ignore

export const listed = (items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)!}`);

/** One field of the published version's form: never prefilled with what a sensitive field hides. */
export function InputControl({ f, value, error, onChange, label: shownLabel, hint: shownHint }: {
  f: StartField; value: string | undefined; error?: string; onChange: (v: string) => void; label?: ReactNode; hint?: ReactNode;
}) {  // prettier-ignore
  const pickers = usePickerForm();
  const label = shownLabel ?? `${nameOf(f)}${f.required ? " (required)" : ""}`;
  const entry = entryOf(f);
  const hint = shownHint ?? (entry === "json" ? [f.description, JSON_HINT].filter(Boolean).join(" ") : (f.description ?? undefined));
  if (pickers && isPicker(f)) return <PickerField f={f} picker={f.picker} value={value} error={error} label={label} hint={hint} onChange={onChange} />;
  if (entry === "yesno") {
    return (
      <Select label={label} hint={hint} error={error} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value)}>
        <option value="">Not given</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </Select>
    );
  }
  if (entry === "choice") {
    return (
      <Select label={label} hint={hint} error={error} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Not given</option>
        {(f.enum ?? []).map((v) => <option key={JSON.stringify(v)} value={JSON.stringify(v)}>{typeof v === "string" ? v : JSON.stringify(v)}</option>)}
      </Select>
    );  // prettier-ignore
  }
  if (entry === "json" && !f.sensitive) {
    return <TextArea label={label} hint={hint} error={error} value={value ?? ""} rows={3} spellCheck={false} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <Field
      label={label} hint={hint} error={error} type={f.sensitive ? "password" : "text"} autoComplete="off" spellCheck={entry === "json" ? false : undefined}
      inputMode={entry === "whole" || entry === "number" ? "decimal" : undefined} value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );  // prettier-ignore
}

/** The published version's form, with the values it starts from: a default its control shows, where one isn't hidden. */
export const startValues = (form: { fields: StartField[] }): ReadonlyMap<string, string> =>
  new Map(form.fields.flatMap((f) => {
    const shown = f.sensitive || f.default === undefined || f.default === null ? null : shownOf(f, f.default);
    return shown === null ? [] : [[f.name, shown] as const];
  }));  // prettier-ignore

/** What a start form's fields show of an input (apps/forms.py reads its root's properties and required): any other
 * keyword at its root (allOf, $ref, if, …) holds rules no field shows, and the input is then entered whole, as JSON. */
export const SHOWN = new Set(["type", "properties", "required", "title", "description", "additionalProperties", "$schema", "$defs", "$comment", "examples"]);
export const fieldsShow = (schema: Record<string, unknown>) => Object.keys(schema).every((k) => SHOWN.has(k) || k.startsWith("x-"));

/** The whole input typed as JSON: an object, its keys as parsed, or why it isn't one (JSON a parse would change, as a
 * field's); nothing typed is an empty input. */
export function wholeOf(text: string): { value: Record<string, unknown> } | { problem: string } {
  const read = parseJson(text);
  if ("problem" in read) return read;
  if (read.value === undefined) return { value: {} };
  return isObject(read.value) ? { value: read.value } : { problem: 'An object, like {"site": "HQ"}.' };
}
