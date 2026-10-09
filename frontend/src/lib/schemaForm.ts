// SPDX-License-Identifier: Apache-2.0
// A step type's config schema read as a form (4c-1): each field's place, label and widget, and the kinds of value it
// takes, by the engine's own markers (sdk/fields.py; engine/graph/schemas.py's literal_on_path, allowed_kinds and
// contains_literal) and the widget contract (§3.3). Nothing here validates: the server does (D19).
import type { NodeType } from "./workflows";

export type Schema = Record<string, unknown>;
export type Kind = "literal" | "ref" | "template" | "cel";
export type Path = (string | number)[];
export type Widget =
  | "formula" | "connection" | "workflow" | "options" | "enum" | "text" | "datetime" | "number" | "integer"
  | "boolean" | "group" | "list" | "map" | "json";  // prettier-ignore

export interface FieldSpec {
  name: string; // the property's or the entry's name, or a list item's index
  path: Path; // where its value sits in the step's config
  pointer: string; // the same, as the JSON pointer the server's problems name
  schema: Schema; // its schema, references followed and a null branch dropped
  root: Schema; // the type's config schema: what references resolve against
  type: NodeType;
  label: string;
  hint: string | null; // its description, its default, a date's format
  required: boolean;
  entry: boolean; // a list's item or a map's entry: emptied, it keeps its place, blank
  widget: Widget; // what edits it (ruling 5)
  base: Widget; // what edits a fixed value of it: its type's widget
  literalOnly: boolean; // `x-dewpoint-literal` here or above: written, never computed
  holdsLiteral: boolean; // it or a part must be written: the whole can't be computed
  holdsSensitive: boolean; // it or a part is sensitive: never shown as JSON
  kinds: Kind[] | null; // `x-dewpoint-kinds` here, or null for any
  sensitive: boolean; // `x-sensitive`: never a fixed value, never shown
  untyped: boolean; // any JSON
  port: boolean; // a dynamic port's name (a switch case's `port`): edges hang on it
  cut: boolean; // shown as JSON: its `$ref` repeats one above it, or it's more than 8 parts deep (ruling 5)
  refs: string[]; // the `$ref`s followed down to it: what makes a repetition visible
}

const KINDS: ReadonlySet<string> = new Set(["literal", "ref", "template", "cel"]);
const BLANK_IS_TEXT: ReadonlySet<Widget> = new Set(["text", "datetime", "enum", "options"]);
const DATE_TIME = "A date and time in ISO 8601, like 2026-10-08T09:00:00Z.";
const MAX_FORM_DEPTH = 8; // a field further down is shown as JSON: no schema can make the form expand forever

export const isObject = (v: unknown): v is Schema => typeof v === "object" && v !== null && !Array.isArray(v);
const without = (s: Schema, key: string): Schema => Object.fromEntries(Object.entries(s).filter(([k]) => k !== key));

export const pointerOf = (path: Path): string =>
  path.map((p) => `/${String(p).replace(/~/g, "~0").replace(/\//g, "~1")}`).join("");

function target(ref: string, root: Schema): Schema {
  if (!ref.startsWith("#/")) return {};
  const found = ref
    .slice(2)
    .split("/")
    .reduce<unknown>((at, k) => (isObject(at) ? at[k.replace(/~1/g, "/").replace(/~0/g, "~")] : undefined), root);
  return isObject(found) ? found : {};
}

/** A schema with its local `$ref` followed, and a `null` branch dropped (`anyOf: [X, {type: "null"}]`, `type: [X,
 * "null"]`): the shape its value has when it's set. Its own keywords win over the target's. */
export function deref(schema: unknown, root: Schema): Schema {
  let s: Schema = isObject(schema) ? schema : {};
  for (let depth = 0; depth < 32 && typeof s.$ref === "string"; depth++) s = { ...target(s.$ref, root), ...without(s, "$ref") };
  for (const key of ["anyOf", "oneOf"]) {
    const branches = s[key];
    if (!Array.isArray(branches)) continue;
    const real = (branches as unknown[]).filter((b) => !(isObject(b) && b.type === "null"));
    if (real.length === 1 && real.length < branches.length) return deref({ ...(isObject(real[0]) ? real[0] : {}), ...without(s, key) }, root);
  }
  if (Array.isArray(s.type)) {
    const real = (s.type as unknown[]).filter((t) => t !== "null");
    if (real.length === 1) return { ...s, type: real[0] };
  }
  return s;
}

/** Whether the schema, or a part of it, carries the marker: engine/graph/schemas.py's contains_literal, for any marker. */
function holds(marker: string, schema: unknown, root: Schema, seen: ReadonlySet<string> = new Set()): boolean {
  if (!isObject(schema)) return false;
  if (schema[marker] === true) return true;
  const ref = schema.$ref;
  if (typeof ref === "string" && !seen.has(ref) && holds(marker, target(ref, root), root, new Set([...seen, ref]))) return true;
  const children: unknown[] = [
    ...(isObject(schema.properties) ? Object.values(schema.properties) : []),
    schema.items,
    schema.additionalProperties,
    ...["anyOf", "oneOf", "allOf", "prefixItems"].flatMap((k) => (Array.isArray(schema[k]) ? (schema[k] as unknown[]) : [])),
    // A sensitive part is also every patternProperties schema, matched or not, and a map whose keys are sensitive:
    // engine/sensitive.py's positions, never fewer (the final review). contains_literal doesn't walk them.
    ...(marker === "x-sensitive"
      ? [...(isObject(schema.patternProperties) ? Object.values(schema.patternProperties) : []), schema.propertyNames]
      : []),
  ];
  return children.some((child) => holds(marker, child, root, seen));
}

/** The widget a value of this schema takes by its type alone. */
function byType(s: Schema): Widget {
  if (Array.isArray(s.enum) && s.enum.length > 0 && (s.enum as unknown[]).every((v) => typeof v === "string")) return "enum";
  switch (s.type) {
    case "string":
      return s.format === "date-time" ? "datetime" : "text";
    case "integer":
      return "integer";
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "object":
      if (isObject(s.properties) && Object.keys(s.properties).length > 0) return "group";
      return s.additionalProperties === false ? "json" : "map";
    case "array":
      return isObject(s.items) && Object.keys(s.items).length > 0 ? "list" : "json";
    default:
      return "json";
  }
}

/** Ruling 5: `x-widget`, then the engine's markers (top-level only), then the type. */
function widgetOf(s: Schema, name: string, top: boolean, type: NodeType): Widget {
  if (s["x-widget"] === "cel") return "formula";
  if (s["x-widget"] === "connection" || typeof s["x-dewpoint-connection"] === "string") return "connection";
  if (top && type.type === "flow.run_workflow" && name === "workflow_id") return "workflow";
  if (top && type.options.includes(name)) return "options";
  return byType(s);
}

function hintOf(s: Schema, widget: Widget, holdsSensitive: boolean): string | null {
  const parts: string[] = [];
  if (typeof s.description === "string" && s.description.trim() !== "") parts.push(s.description.trim());
  if (widget === "datetime") parts.push(DATE_TIME);
  // A default is said, unless it is or holds a sensitive value (ledger M25: a secret is never repeated).
  if (!holdsSensitive && s.default !== undefined && s.default !== null) {
    parts.push(`If empty: ${typeof s.default === "string" ? s.default : JSON.stringify(s.default)}.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

function make(
  type: NodeType, root: Schema, name: string, path: Path, raw: unknown, required: boolean, entry: boolean,
  literalAbove: boolean, refsAbove: string[],
): FieldSpec {  // prettier-ignore
  const own = isObject(raw) ? raw : {};
  const ref = typeof own.$ref === "string" ? own.$ref : null;
  const cut = (ref !== null && refsAbove.includes(ref)) || path.length > MAX_FORM_DEPTH;
  const schema = deref(own, root);
  const widget = cut ? "json" : widgetOf(schema, name, path.length === 1, type);
  const sensitive = own["x-sensitive"] === true || schema["x-sensitive"] === true;
  const holdsSensitive = holds("x-sensitive", own, root);
  const kinds = own["x-dewpoint-kinds"] ?? schema["x-dewpoint-kinds"];
  return {
    name, path, pointer: pointerOf(path), schema, root, type,
    label: typeof schema.title === "string" && schema.title.trim() !== "" ? schema.title : name,
    hint: hintOf(schema, widget, holdsSensitive),
    required, entry, widget, base: cut ? "json" : byType(schema),
    literalOnly: literalAbove || own["x-dewpoint-literal"] === true || schema["x-dewpoint-literal"] === true,
    holdsLiteral: holds("x-dewpoint-literal", own, root),
    holdsSensitive,
    kinds: Array.isArray(kinds) ? (kinds as unknown[]).filter((k): k is Kind => typeof k === "string" && KINDS.has(k)) : null,
    sensitive,
    untyped: !["type", "enum", "const", "properties", "items"].some((k) => k in schema),
    port: type.dynamic_ports !== null && path.length === 3 && path[0] === type.dynamic_ports && typeof path[1] === "number" && path[2] === "port",
    cut,
    refs: ref === null ? refsAbove : [...refsAbove, ref],
  };  // prettier-ignore
}

function propertiesIn(type: NodeType, root: Schema, schema: Schema, base: Path, literalAbove: boolean, refs: string[]): FieldSpec[] {
  const props = isObject(schema.properties) ? schema.properties : {};
  const required = Array.isArray(schema.required) ? (schema.required as unknown[]) : [];
  return Object.entries(props).map(([name, raw]) =>
    make(type, root, name, [...base, name], raw, required.includes(name), false, literalAbove, refs),
  );
}

/** A type's settings: its config schema's top-level properties, in the schema's order. */
export function fieldsOf(type: NodeType): FieldSpec[] {
  const root = isObject(type.config_schema) ? type.config_schema : {};
  return propertiesIn(type, root, deref(root, root), [], false, []);
}

/** A group's parts: its properties. */
export const propertiesOf = (f: FieldSpec): FieldSpec[] =>
  f.cut ? [] : propertiesIn(f.type, f.root, f.schema, f.path, f.literalOnly, f.refs);

/** A list's item, labelled by its place ("Cases, item 1"). */
export const itemOf = (f: FieldSpec, index: number): FieldSpec => ({
  ...make(f.type, f.root, String(index), [...f.path, index], f.schema.items, true, true, f.literalOnly, f.refs),
  label: `${f.label}, item ${index + 1}`,
});

/** A map's entry: its value takes the map's `additionalProperties`, or any JSON. */
export const entryOf = (f: FieldSpec, name: string): FieldSpec =>
  make(f.type, f.root, name, [...f.path, name], isObject(f.schema.additionalProperties) ? f.schema.additionalProperties : {}, true, true, f.literalOnly, f.refs);  // prettier-ignore

/** Setup holds the required top-level fields, Options the rest, each in the schema's order (ruling 3). */
export const tabsOf = (fields: FieldSpec[]) => ({
  setup: fields.filter((f) => f.required),
  options: fields.filter((f) => !f.required),
});

/** Where the engine takes a fixed value: not in a sensitive field (sensitive.literal), and `literal` among its kinds. */
export const canFixed = (f: FieldSpec): boolean => !f.sensitive && (f.kinds === null || f.kinds.includes("literal"));

/** Where it takes a formula: no literal-only marker on the path or inside (value.literal_only), `cel` among its kinds. */
export const canFormula = (f: FieldSpec): boolean =>
  !f.literalOnly && !f.holdsLiteral && (f.kinds === null || f.kinds.includes("cel"));

/** A field empty so far starts as a formula when its widget is one, when it's any JSON, or when it takes nothing else. */
export const startsAsFormula = (f: FieldSpec): boolean =>
  canFormula(f) && (f.widget === "formula" || f.widget === "json" || !canFixed(f));

/** What emptying a field writes: nothing (it's removed, so its default applies), or, for a list's item or a map's
 * entry, a blank that keeps its place. */
export const emptyOf = (f: FieldSpec): unknown => (f.entry ? (BLANK_IS_TEXT.has(f.widget) ? "" : null) : undefined);
