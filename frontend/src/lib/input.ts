// SPDX-License-Identifier: Apache-2.0
// A workflow's input (4c-3b; the mockups' InputFields and InputMist boards): `settings.input_schema` read as a list of
// form fields, and written back one field at a time, or replaced by a trigger topic's shape. What the list can't show
// (a list, an object of fields, a field with rules of its own) stays as written, read only: Edit as JSON changes it.
// A field may be a choice from a connection: a start-form picker (plugins-3 D19; the 4f-3 design §5.7). Every change
// keeps what it doesn't touch, key order included. The server checks the schema (D18).
import { CEL_WORDS } from "./config";
import { deref, isObject, type Schema } from "./schemaForm";
import type { GraphDoc } from "./workflows";

export type FieldType = "text" | "whole" | "number" | "yesno" | "choice" | "datetime" | "picker";

export const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "whole", label: "Whole number" },
  { value: "number", label: "Number" },
  { value: "yesno", label: "Yes or no" },
  { value: "choice", label: "Choice" },
  { value: "datetime", label: "Date and time" },
  { value: "picker", label: "Choice from a connection" },
];

/** A start-form picker (`x-dewpoint-picker`): a node type's options field, listed through a connection. `connection` is
 * null where none is written (a file imported with its binding left open, §4.5). */
export type InputPicker = { node: string; field: string; connection: string | null };

export interface InputField {
  name: string;
  label: string; // its `title`; empty for none
  type: FieldType;
  required: boolean;
  sensitive: boolean; // `x-sensitive`: kept apart from run history
  description: string;
  default?: unknown; // present only when written
  values: string[]; // a Choice's
  picker?: InputPicker; // a Choice from a connection's
}

/** A field as the list shows it, or one it can't: then only its name, whether it's required, and what it is. */
export type InputRow = { kind: "field"; field: InputField } | { kind: "other"; name: string; required: boolean; what: string };

/** The keys a field the list shows may have: anything else is a rule of its own the list would lose. */
const PICKER = "x-dewpoint-picker";
// The fields' order, a list beside them: stored JSON keeps no key order, so the author's travels here (F3).
const ORDER = "x-dewpoint-order";
const PLAIN = new Set(["type", "title", "description", "default", "x-sensitive", "format", "enum", PICKER]);
const PICKER_KEYS = new Set(["node", "field", "connection"]);

/** A picker as a field reads it: a node and a field, and its connection when written; null for any other shape, or
 * beside a default, values, a format or sensitivity (one rule with the start forms, §5.2). */
function pickerOf(s: Schema): InputPicker | null {
  const p = s[PICKER];
  if (s.type !== "string" || ["enum", "format", "default", "x-sensitive"].some((k) => k in s) || !isObject(p)) return null;
  if (Object.keys(p).some((k) => !PICKER_KEYS.has(k)) || typeof p.node !== "string" || typeof p.field !== "string") return null;
  if ("connection" in p && typeof p.connection !== "string") return null;
  return { node: p.node, field: p.field, connection: typeof p.connection === "string" ? p.connection : null };
}
const TYPE_OF: Record<string, FieldType> = { string: "text", integer: "whole", number: "number", boolean: "yesno" };
export const RESERVED = new Set(["rows", "row_count"]); // a CSV's (engine/graph/csv.py), never a field
const NAME = /^[a-z][a-z0-9_]{0,62}$/;

const propertiesOf = (schema: Schema): Schema => (isObject(schema.properties) ? schema.properties : {});
const requiredOf = (schema: Schema): string[] =>
  Array.isArray(schema.required) ? (schema.required as unknown[]).filter((r): r is string => typeof r === "string") : [];

/** What a property the list can't show is, in a few words. */
function what(s: Schema, root: Schema): string {
  const d = deref(s, root);
  if (d.type === "array") return "a list";
  if (d.type === "object" || isObject(d.properties)) return "an object of fields";
  if (typeof d.type === "string" && TYPE_OF[d.type]) return `${FIELD_TYPES.find((t) => t.value === TYPE_OF[d.type as string])!.label.toLowerCase()} with rules of its own`;
  return "a value of its own shape";
}

/** A property as a field, or null when the list can't show it as one without losing what it says. */
function fieldOf(name: string, s: unknown, required: boolean): InputField | null {
  if (!isObject(s) || Object.keys(s).some((k) => !PLAIN.has(k))) return null;
  const sensitive = s["x-sensitive"] === true;
  if ("x-sensitive" in s && typeof s["x-sensitive"] !== "boolean") return null;
  if (s.title !== undefined && typeof s.title !== "string") return null;
  if (s.description !== undefined && typeof s.description !== "string") return null;
  let type: FieldType | undefined;
  let values: string[] = [];
  let picker: InputPicker | null = null;
  if (PICKER in s) {
    picker = pickerOf(s);
    if (!picker) return null;
    type = "picker";
  } else if (s.enum !== undefined) {
    if (s.type !== "string" || s.format !== undefined || !Array.isArray(s.enum) || !s.enum.every((v) => typeof v === "string")) return null;
    type = "choice";
    values = s.enum;
  } else if (s.format !== undefined) {
    if (s.type !== "string" || s.format !== "date-time") return null;
    type = "datetime";
  } else if (typeof s.type === "string") type = TYPE_OF[s.type];
  if (!type) return null;
  return {
    name, label: (s.title) ?? "", type, required, sensitive, description: (s.description) ?? "",
    values, ...("default" in s ? { default: s.default } : {}), ...(picker ? { picker } : {}),
  };  // prettier-ignore
}

/** The fields' names in the form's order: those the schema's order lists, as it lists them (a name that isn't a field,
 * a repeat or anything not a name passed over), then the others, as stored. */
export function fieldOrder(schema: Schema): string[] {
  const props = propertiesOf(schema);
  const listed: unknown[] = Array.isArray(schema[ORDER]) ? schema[ORDER] : [];
  const first = [...new Set(listed.filter((n): n is string => typeof n === "string" && Object.hasOwn(props, n)))];
  return [...first, ...Object.keys(props).filter((n) => !first.includes(n))];
}

/** The input's fields, in the form's order. */
export function inputRows(schema: Schema): InputRow[] {
  const required = new Set(requiredOf(schema));
  const props = propertiesOf(schema);
  return fieldOrder(schema).map((name): InputRow => {
    const s = props[name];
    const field = fieldOf(name, s, required.has(name));
    return field ? { kind: "field", field } : { kind: "other", name, required: required.has(name), what: what(isObject(s) ? s : {}, schema) };
  });
}

/** A field as the schema writes it: its keys in a fixed order, only those it has. */
function schemaOf(f: InputField): Schema {
  const out: Schema = { type: f.type === "whole" ? "integer" : f.type === "number" ? "number" : f.type === "yesno" ? "boolean" : "string" };
  if (f.label !== "") out.title = f.label;
  if (f.description !== "") out.description = f.description;
  if (f.type === "datetime") out.format = "date-time";
  if (f.type === "choice") out.enum = f.values;
  if (f.type === "picker" && f.picker) {
    const { node, field, connection } = f.picker;
    out[PICKER] = { node, field, ...(connection !== null ? { connection } : {}) };
  }
  if (f.sensitive) out["x-sensitive"] = true;
  if ("default" in f) out.default = f.default;
  return out;
}

/** Whether a default still fits a field after its type or values changed: one that doesn't goes with the change. */
function fits(f: InputField, v: unknown): boolean {
  switch (f.type) {
    case "text":
    case "datetime":
      return typeof v === "string";
    case "whole":
      return typeof v === "number" && Number.isInteger(v);
    case "number":
      return typeof v === "number";
    case "yesno":
      return typeof v === "boolean";
    case "choice":
      return typeof v === "string" && f.values.includes(v);
    case "picker":
      return false; // a picked value is the person's, never a default
  }
}

const withProperties = (schema: Schema, properties: Schema, required: string[]): Schema => {
  const out: Schema = { ...schema, properties };
  if (required.length > 0) out.required = required;
  else delete out.required;
  return out;
};

/** The schema with its fields' order written; none without a field. */
const withOrder = (schema: Schema, order: string[]): Schema => {
  const out: Schema = { ...schema };
  if (order.length > 0) out[ORDER] = order;
  else delete out[ORDER];
  return out;
};

/** The schema as Edit as JSON shows it: its fields written in the form's order, which the text then says. */
export function formOrdered(schema: Schema): Schema {
  const props = propertiesOf(schema);
  const out: Schema = isObject(schema.properties) ? { ...schema, properties: Object.fromEntries(fieldOrder(schema).map((n) => [n, props[n]])) } : { ...schema };
  delete out[ORDER];
  return out;
}

/** The schema as Edit as JSON's text says it: its fields' order the order they're written in, a list typed there
 * replaced by it (ruled). */
export const orderAsWritten = (schema: Schema): Schema => withOrder(schema, Object.keys(propertiesOf(schema)));

/** The schema with one field changed as `patch` says: a sensitive field has no default, a default that no longer fits
 * its type or values goes, a picker goes with its type, and `required` follows. A field the list can't show is left as
 * it is. */
export function setField(schema: Schema, name: string, patch: Partial<Omit<InputField, "name">>): Schema {
  const row = inputRows(schema).find((r) => r.kind === "field" && r.field.name === name);
  if (!row || row.kind !== "field") return schema;
  const next: InputField = { ...row.field, ...patch };
  if (next.type !== "choice") next.values = [];
  if (next.type !== "picker") delete next.picker;
  else next.sensitive = false;
  if (next.sensitive || ("default" in next && !fits(next, next.default)) || ("default" in patch && patch.default === undefined)) delete next.default;
  const properties = { ...propertiesOf(schema), [name]: schemaOf(next) };
  const was = requiredOf(schema);
  return withProperties(schema, properties, next.required ? (was.includes(name) ? was : [...was, name]) : was.filter((r) => r !== name));
}

/** Why a field can't take `to` as its name, or null: steps read it as `trigger.<name>`. */
export function nameProblem(schema: Schema, from: string | null, to: string): string | null {
  if (!NAME.test(to) || CEL_WORDS.has(to)) return "Lowercase letters, digits and _, starting with a letter; not in, true, false or null.";
  if (RESERVED.has(to)) return "`rows` and `row_count` are a CSV file's: declare the file, and its rows arrive there.";
  if (to !== from && Object.hasOwn(propertiesOf(schema), to)) return "Another field has this name.";
  return null;
}

/** The schema with a field renamed, in its place, its `required` entry following. */
export function renameField(schema: Schema, from: string, to: string): Schema {
  if (from === to || !Object.hasOwn(propertiesOf(schema), from)) return schema;
  const properties = Object.fromEntries(Object.entries(propertiesOf(schema)).map(([k, v]) => [k === from ? to : k, v]));
  const renamed = withProperties(schema, properties, requiredOf(schema).map((r) => (r === from ? to : r)));
  return withOrder(renamed, fieldOrder(schema).map((n) => (n === from ? to : n)));
}

/** The schema with a new, optional text field at the end, named `field_<n>` with the first n not taken. */
export function addField(schema: Schema): { schema: Schema; name: string } {
  let n = Object.keys(propertiesOf(schema)).length + 1;
  while (Object.hasOwn(propertiesOf(schema), `field_${n}`)) n++;
  const name = `field_${n}`;
  const added = withProperties(schema, { ...propertiesOf(schema), [name]: { type: "string" } }, requiredOf(schema));
  return { schema: withOrder(added, [...fieldOrder(schema), name]), name };
}

export function removeField(schema: Schema, name: string): Schema {
  const properties = Object.fromEntries(Object.entries(propertiesOf(schema)).filter(([k]) => k !== name));
  const removed = withProperties(schema, properties, requiredOf(schema).filter((r) => r !== name));
  return withOrder(removed, fieldOrder(schema).filter((n) => n !== name));
}

/** Where a field is in the settings, as a pointer (RFC 6901): what its held edits and the server's problems name. */
export const fieldPointer = (name: string) => `/settings/input_schema/properties/${name.replaceAll("~", "~0").replaceAll("/", "~1")}`;

/** The input field a pointer is in (one under `fieldPointer`'s), its name unescaped; null outside them. */
export function inputFieldOf(pointer: string): string | null {
  const m = /^\/settings\/input_schema\/properties\/([^/]+)(?:\/|$)/.exec(pointer);
  return m ? m[1]!.replaceAll("~1", "/").replaceAll("~0", "~") : null;
}

/** The input schema of a draft: an object schema with no fields when it has none. */
export const inputOf = (doc: GraphDoc): Schema => (isObject(doc.settings?.input_schema) ? doc.settings.input_schema : { type: "object" });

/** The draft with these settings: each key given replaced, `undefined` removing it, the rest as they were. */
export function setSettings(doc: GraphDoc, patch: Record<string, unknown>): GraphDoc {
  const settings: Record<string, unknown> = { ...(doc.settings ?? {}) };
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) delete settings[k];
    else settings[k] = v;
  }
  return { ...doc, settings: settings };
}

const canonical = (v: unknown): string =>
  JSON.stringify(v, (_, x: unknown) => (isObject(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x));

/** A schema without its fields' order. */
function unordered(v: unknown): unknown {
  if (!isObject(v) || !Object.hasOwn(v, ORDER)) return v;
  const out: Schema = { ...v };
  delete out[ORDER];
  return out;
}

/** Whether two schemas say the same, whatever their keys' order or their fields': a topic's shape is one in any. */
export const sameSchema = (a: unknown, b: unknown): boolean => canonical(unordered(a)) === canonical(unordered(b));

/** The topic whose shape the input is, of a trigger type's: null when it's none of them. */
export function topicShaped(schema: Schema, topics: Record<string, unknown>): string | null {
  return Object.keys(topics).find((t) => sameSchema(schema, topics[t])) ?? null;
}

/** A row of an event's shape, read only: where a step reads it, what it is, and whether it may be missing. */
export interface ShapeRow {
  path: string;
  what: string;
  optional: boolean;
}

const KIND: Record<string, string> = { string: "text", integer: "whole number", number: "number", boolean: "yes or no", object: "object", array: "list" };

function kindWords(s: Schema): string {
  if (typeof s.const === "string") return `text, always ${s.const}`;
  return typeof s.type === "string" ? (KIND[s.type] ?? s.type) : "a value";
}

/** A topic's shape as rows (the InputMist board): its own fields, then one event's, at most `max` of those. */
export function shapeRows(schema: Schema, topic: string, max = 6): { rows: ShapeRow[]; more: boolean } {
  const rows: ShapeRow[] = [];
  const required = new Set(requiredOf(schema));
  let event: Schema | null = null;
  for (const [name, raw] of Object.entries(propertiesOf(schema))) {
    const s = deref(raw, schema);
    if (s.type === "array" && isObject(s.items)) {
      event = deref(s.items, schema);
      rows.push({ path: `trigger.${name}`, what: `list of ${topic.replaceAll("-", " ")}`, optional: !required.has(name) });
    } else rows.push({ path: `trigger.${name}`, what: kindWords(s), optional: !required.has(name) });
  }
  if (!event) return { rows, more: false };
  const fields = Object.entries(propertiesOf(event));
  const inEvent = new Set(requiredOf(event));
  for (const [name, raw] of fields.slice(0, max)) rows.push({ path: `[ ].${name}`, what: kindWords(deref(raw, schema)), optional: !inEvent.has(name) });
  return { rows, more: fields.length > max };
}
