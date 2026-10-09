// SPDX-License-Identifier: Apache-2.0
// A step's values, and the drawer's changes to a draft, as pure functions (4c-1). A value is fixed (any JSON) or
// computed: `{"$value": {kind, ...}}` (engine/graph/values.py), a formula (`cel`), a reference (`ref`) or text with
// references (`template`); a `literal` envelope is a fixed value written the long way. Each change returns a new
// document and keeps what it doesn't touch as it was, byte for byte.
import { edgesOf, findNode, nodesOf, portOf, portsOf, sameId } from "./graph";
import { isObject, type Path } from "./schemaForm";
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

export const ENVELOPE = "$value";
export const MAX_FORMULA = 16_384; // engine/graph/values.py's MAX_CEL
export const CEL_WORDS: ReadonlySet<string> = new Set(["in", "true", "false", "null"]); // CEL can't select them
const KEY = /^[a-z][a-z0-9_]{0,62}$/; // engine/graph/model.py's KEY_PATTERN: a draft breaking it isn't saved
const PORT = /^[a-z][a-z0-9_]{0,30}$/; // and its PORT_PATTERN, which every edge's port must match

export type ValueKind = "literal" | "ref" | "template" | "cel";
export type StepOptions = NonNullable<GraphNode["options"]>;
export interface Changed {
  doc: GraphDoc;
  dropped: GraphEdge[]; // the edges that left a port the change took away
}

const bodyOf = (value: unknown): Record<string, unknown> =>
  isObject(value) && isObject(value[ENVELOPE]) ? value[ENVELOPE] : {};

/** A computed value's kind; "unknown" for an object with `$value` the engine can't read; null for a fixed value. */
export function kindOf(value: unknown): ValueKind | "unknown" | null {
  if (!isObject(value) || !(ENVELOPE in value)) return null;
  const kind = bodyOf(value).kind;
  return kind === "literal" || kind === "ref" || kind === "template" || kind === "cel" ? kind : "unknown";
}

export const formula = (expr: string) => ({ [ENVELOPE]: { kind: "cel", expr } });
/** A fixed value written the long way: data, whatever it holds, `$value` included (ruling 15). */
export const literal = (value: unknown) => ({ [ENVELOPE]: { kind: "literal", value } });

export function formulaOf(value: unknown): string {
  const expr = bodyOf(value).expr;
  return kindOf(value) === "cel" && typeof expr === "string" ? expr : "";
}

/** A fixed value as written: a `literal` envelope's own value, or the value itself. */
export const fixedOf = (value: unknown): unknown => (kindOf(value) === "literal" ? bodyOf(value).value : value);

/** A reference as its path, or a template as its parts, each reference in braces. */
export function referenceText(value: unknown): string {
  const body = bodyOf(value);
  if (body.kind === "ref") return typeof body.path === "string" ? body.path : "";
  if (body.kind !== "template" || !Array.isArray(body.parts)) return "";
  return (body.parts as unknown[])
    .map((p) => (!isObject(p) ? "" : typeof p.ref === "string" ? `{${p.ref}}` : typeof p.text === "string" ? p.text : ""))
    .join("");
}

/** A reference with no default: the same path reads the same value as a formula. */
export const isPlainRef = (value: unknown): boolean => kindOf(value) === "ref" && !("default" in bodyOf(value));

/** The first number in a value JSON.parse may have changed: one that isn't finite (`1e400`), or a whole number past
 * 2^53, whatever its notation (`9007199254740993`, `…993.0`, `…993e0` all round). Null when there's none. */
function changedNumber(value: unknown): "infinite" | "rounded" | null {
  const stack = [value];
  while (stack.length > 0) {
    const at = stack.pop();
    if (typeof at === "number" && !Number.isFinite(at)) return "infinite";
    if (typeof at === "number" && Number.isInteger(at) && !Number.isSafeInteger(at)) return "rounded";
    if (Array.isArray(at)) stack.push(...(at as unknown[]));
    else if (isObject(at)) stack.push(...Object.values(at));
  }
  return null;
}

/** JSON text as a value the draft can keep (rulings 7 and 15): refused when it doesn't parse, or when parsing may have
 * changed a number, as the server keeps what's sent. Empty text is no value. */
export function parseJson(text: string): { value: unknown } | { problem: string } {
  if (text.trim() === "") return { value: undefined };
  let value: unknown;
  try {
    value = JSON.parse(text) as unknown;
  } catch {
    return { problem: "This isn't valid JSON, so it isn't saved." };
  }
  const changed = changedNumber(value);
  if (changed === "infinite") return { problem: "A number here is too large to keep, so it isn't saved." };
  if (changed === "rounded") return { problem: "A whole number here is too large to keep exactly, so it isn't saved." };
  return { value };
}

export const MAX_DEPTH = 64; // engine/graph/model.py: containers nested from the graph down, the graph being level 1
export const MAX_VALUES = 2_000; // and its envelopes: references, templates, formulas, literals

/** Why the graph's format would refuse the document (engine/graph/model.py's `_admission_problems`), or null: a
 * number that isn't finite, a container nested past 64 levels, more than 2,000 envelopes. The save would fail whole,
 * so the drawer writes nothing that breaks them (ruling 7). */
export function admission(doc: GraphDoc): string | null {
  let values = 0;
  const stack: [unknown, number][] = [[doc, 1]];
  while (stack.length > 0) {
    const [value, depth] = stack.pop()!;
    if (typeof value === "number" && !Number.isFinite(value)) return "A number in the draft isn't finite, so it couldn't be saved.";
    if (typeof value !== "object" || value === null) continue;
    if (depth > MAX_DEPTH) return `Values can be nested at most ${MAX_DEPTH} levels deep.`;
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) stack.push([item, depth + 1]);
    } else {
      if (ENVELOPE in value) values++;
      for (const item of Object.values(value)) stack.push([item, depth + 1]);
    }
  }
  return values > MAX_VALUES ? "A workflow can hold at most 2,000 references, templates and formulas." : null;
}

export function valueAt(root: unknown, path: Path): unknown {
  let at = root;
  for (const key of path) {
    if (typeof key === "number" && Array.isArray(at)) at = (at as unknown[])[key];
    else if (typeof key === "string" && isObject(at)) at = at[key];
    else return undefined;
  }
  return at;
}

// Lineage (4c-1, ruling 18): each copy `setAt` makes descends from what it copied. An item or a list edited in place
// keeps its root through every copy; a list rebuilt by a move, a removal, a JSON edit or an import starts a root of
// its own. An
// unapplied edit is applied only where its lists and items are still the ones it was typed in (the review of
// revision 4: two items can hold equal values).
const roots = new WeakMap<object, object>();
export const rootOf = (o: object): object => roots.get(o) ?? o;
function descends<T extends object>(copy: T, from: unknown): T {
  if (typeof from === "object" && from !== null) roots.set(copy, rootOf(from));
  return copy;
}

/** `root` with `value` at `path`, copied along the path only, each copy keeping its lineage. Undefined removes a
 * property, or splices a list's item. */
export function setAt(root: unknown, path: Path, value: unknown): unknown {
  const [key, ...rest] = path;
  if (key === undefined) return value;
  if (typeof key === "number") {
    const list = Array.isArray(root) ? [...(root as unknown[])] : [];
    // A removal moves every item after it: a new lineage, as a move's. Only an edit in place keeps the list's (the
    // review of revision 5: in [5, 5, 7], removing the first 5 and undoing it must not let an edit typed on the other
    // 5 land on the first).
    if (rest.length === 0 && value === undefined) {
      list.splice(key, 1);
      return list;
    }
    list[key] = setAt(list[key], rest, value);
    return descends(list, root);
  }
  const object = isObject(root) ? root : {};
  if (rest.length === 0 && value === undefined) {
    return descends(Object.fromEntries(Object.entries(object).filter(([k]) => k !== key)), root);
  }
  return descends({ ...object, [key]: setAt(object[key], rest, value) }, root);
}

function withNode(doc: GraphDoc, nodeId: string, node: GraphNode): GraphDoc {
  return { ...doc, nodes: nodesOf(doc).map((n) => (sameId(n.id, nodeId) ? node : n)) };
}

/** The document without the edges that left a port `before` had and `after` hasn't; edges from a port the step never
 * had (an import's) stay: the validator reports them. */
function dropLost(doc: GraphDoc, before: GraphNode, after: GraphNode, type: NodeType | undefined): Changed {
  const kept = new Set(portsOf(after, type));
  const lost = portsOf(before, type).filter((p) => !kept.has(p));
  const dropped = edgesOf(doc).filter((e) => sameId(e.from.node, before.id) && lost.includes(portOf(e)));
  if (dropped.length === 0) return { doc, dropped };
  return { doc: { ...doc, edges: edgesOf(doc).filter((e) => !dropped.includes(e)) }, dropped };
}

export function setConfig(doc: GraphDoc, nodeId: string, path: Path, value: unknown, type: NodeType | undefined): Changed {
  const before = findNode(doc, nodeId);
  if (!before) return { doc, dropped: [] };
  const after = { ...before, config: setAt(before.config ?? {}, path, value) as Record<string, unknown> };
  return dropLost(withNode(doc, nodeId, after), before, after, type);
}

/** What a step sets for itself; what it leaves out takes the type's defaults, and a failure fails the run by default,
 * so "fail" isn't written. */
export function setOptions(doc: GraphDoc, nodeId: string, options: StepOptions, type: NodeType | undefined): Changed {
  const before = findNode(doc, nodeId);
  if (!before) return { doc, dropped: [] };
  const own = Object.fromEntries(
    Object.entries(options).filter(([k, v]) => v !== undefined && v !== null && !(k === "on_error" && v === "fail")),
  ) as StepOptions;
  const after: GraphNode = Object.keys(own).length > 0
    ? { ...before, options: own }
    : (Object.fromEntries(Object.entries(before).filter(([k]) => k !== "options")) as GraphNode);  // prettier-ignore
  return dropLost(withNode(doc, nodeId, after), before, after, type);
}

/** A dynamic port renamed where its entry sits (a switch case's `port`): its edges follow it. Refused, with the reason,
 * for a name the graph's format refuses or one another port of the step has: edges hang on port names (ruling 9). */
export function renamePort(doc: GraphDoc, nodeId: string, index: number, name: string, type: NodeType): { doc: GraphDoc } | { problem: string } {
  const node = findNode(doc, nodeId);
  const field = type.dynamic_ports;
  if (!node || field === null) return { doc };
  const old = valueAt(node.config ?? {}, [field, index, "port"]);
  if (old === name) return { doc };
  if (!PORT.test(name)) {
    return { problem: "A port's name starts with a lowercase letter, then lowercase letters, digits or _, up to 31 characters." };
  }
  if (portsOf(node, type).includes(name)) return { problem: `Another port of this step is already called ${name}.` };
  const after = { ...node, config: setAt(node.config ?? {}, [field, index, "port"], name) as Record<string, unknown> };
  const next = withNode(doc, nodeId, after);
  // Another entry may still declare the old name (a duplicate): its edges are that entry's then.
  if (typeof old !== "string" || portsOf(after, type).includes(old)) return { doc: next };
  return {
    doc: {
      ...next,
      edges: edgesOf(next).map((e) => (sameId(e.from.node, nodeId) && portOf(e) === old ? { ...e, from: { ...e.from, port: name } } : e)),
    },
  };
}

/** A map's entry renamed in place, keeping its order; refused, with the reason, when the name is empty, `$value`
 * (ruling 15) or another entry's. */
export function renameEntry(doc: GraphDoc, nodeId: string, path: Path, from: string, to: string): { doc: GraphDoc } | { problem: string } {
  const node = findNode(doc, nodeId);
  const map = node ? valueAt(node.config ?? {}, path) : undefined;
  if (!node || !isObject(map) || from === to) return { doc };
  if (to === "") return { problem: "A name can't be empty." };
  if (to === ENVELOPE) return { problem: "A name can't be $value: the engine would read the whole value as computed." };
  if (Object.hasOwn(map, to)) return { problem: `There's already one called ${to}.` };
  const renamed = Object.fromEntries(Object.entries(map).map(([k, v]) => [k === from ? to : k, v]));
  return { doc: withNode(doc, nodeId, { ...node, config: setAt(node.config ?? {}, path, renamed) as Record<string, unknown> }) };
}

/** The first `case_N` no port of the step has: a new case's port. */
export function freePort(node: GraphNode, type: NodeType): string {
  const taken = new Set(portsOf(node, type));
  for (let n = 1; ; n++) if (!taken.has(`case_${n}`)) return `case_${n}`;
}

/** Why a step can't take this key, or null (ruling 11). The pattern is the graph's format; the rest the validator's. */
export function keyProblem(doc: GraphDoc, nodeId: string, key: string): string | null {
  if (!KEY.test(key)) return "A key starts with a lowercase letter, then lowercase letters, digits or _, up to 63 characters.";
  if (CEL_WORDS.has(key)) return `${key} can't be a key: formulas couldn't name the step.`;
  if (nodesOf(doc).some((n) => n.key === key && !sameId(n.id, nodeId))) return `Another step is already called ${key}.`;
  return null;
}

/** A step's key changed, with every structured reference to it (`steps.<key>`, `loops.<key>`) in every step's config
 * and the workflow's outputs. Formulas aren't parsed here: they keep their text, and `mentions` counts those whose
 * text mentions the old key as a word, a reference or not (ruling 11). A fixed value's data is data, never
 * rewritten. */
export function renameKey(doc: GraphDoc, nodeId: string, key: string): { doc: GraphDoc; mentions: number } {
  const node = findNode(doc, nodeId);
  if (!node || node.key === key) return { doc, mentions: 0 };
  const old = node.key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const path = new RegExp(`^((?:steps|loops)\\.)${old}(?=$|[.[])`);
  const mentioned = new RegExp(`(?<![\\w$])${old}(?![\\w$])`);
  let mentions = 0;
  const rename = (p: unknown) => (typeof p === "string" && path.test(p) ? p.replace(path, `$1${key}`) : p);
  const walk = (v: unknown): unknown => {
    if (Array.isArray(v)) {
      const out = (v as unknown[]).map(walk);
      return out.every((x, i) => x === (v as unknown[])[i]) ? v : out;
    }
    if (!isObject(v)) return v;
    const kind = kindOf(v);
    const body = bodyOf(v);
    if (kind === "ref") {
      const next = rename(body.path);
      return next === body.path ? v : { [ENVELOPE]: { ...body, path: next } };
    }
    if (kind === "template" && Array.isArray(body.parts)) {
      const before = body.parts as unknown[];
      const parts = before.map((p) => {
        if (!isObject(p)) return p;
        const ref = rename(p.ref);
        return ref === p.ref ? p : { ...p, ref };
      });
      return parts.every((p, i) => p === before[i]) ? v : { [ENVELOPE]: { ...body, parts } };
    }
    if (kind === "cel") {
      if (typeof body.expr === "string" && mentioned.test(body.expr)) mentions++;
      return v;
    }
    if (kind !== null) return v; // a literal's value, or an envelope the engine can't read: kept as written
    const entries = Object.entries(v).map(([k, x]) => [k, walk(x)] as const);
    return entries.every(([k, x]) => x === v[k]) ? v : Object.fromEntries(entries);
  };
  const nodes = nodesOf(doc).map((n) => {
    const config = n.config === undefined ? undefined : (walk(n.config) as Record<string, unknown>);
    const renamed = sameId(n.id, nodeId) ? { ...n, key } : n;
    return config === n.config ? renamed : { ...renamed, config };
  });
  const outputs = doc.settings?.outputs === undefined ? undefined : (walk(doc.settings.outputs) as Record<string, unknown>);
  const settings = doc.settings && outputs !== doc.settings.outputs ? { ...doc.settings, outputs } : doc.settings;
  return { doc: { ...doc, nodes, ...(settings ? { settings } : {}) }, mentions };
}
