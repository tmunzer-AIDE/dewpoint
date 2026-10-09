// SPDX-License-Identifier: Apache-2.0
// Edits typed but not yet in the draft (4c-1, ruling 18): JSON being typed or refused; a map entry's, a port's or the
// key's name; a number or a limit that doesn't parse; text or a formula a write refused. The editor keeps them,
// never the control, so a tab, a toggle or a closed drawer can't lose them. Each is applied when it can be, and said,
// with its reason, while it can't.
import {
  admission, formula, keyProblem, literal, parseJson, renameEntry, renameKey, renamePort, rootOf, setConfig, setOptions,
  valueAt, type Changed,
} from "./config";  // prettier-ignore
import { findNode, idKey, portOf, sameId } from "./graph";
import { isObject, type Path } from "./schemaForm";
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

export type UnappliedKind = "text" | "json" | "number" | "formula" | "port" | "name" | "key" | "limit";

export interface Unapplied {
  id: string; // unappliedId(node, kind, pointer)
  node: string; // the step's id, as the draft writes it
  kind: UnappliedKind;
  pointer: string; // where it goes: in the step's config; "/options/<name>" for a limit; "" for the key
  path: Path; // the same as a path: a limit's is [its name]; a name's is its map's; the key's is []
  label: string; // the field's label, for the question that lists it
  text: string;
  why: string | null; // why it isn't in the draft; null while it's being typed
  base: string; // what it was typed over, as JSON (baseOf): it's applied only where that's still what's there
  lineage: unknown[]; // the roots of the lists and items on its path (lineageOf): the same ones, not equal ones
  entry?: boolean; // emptied, a list's item or a map's entry blanks to null rather than going
  literal?: boolean; // its value is a `literal` envelope's payload, written back as one (ruling 15)
  whole?: boolean; // a number: whole
  from?: string; // a map entry's name in the draft
}

/** What a control supplies; the editor adds its step, its kind, where it goes and what it was typed over. */
export type Holding = Omit<Unapplied, "id" | "node" | "kind" | "pointer" | "base" | "lineage">;

export interface Applied extends Changed {
  said: string | null; // what to announce: a field's own edit says nothing (ruling 8)
  note: string | null; // what the drawer says after it, until the next edit: a rename's formulas (ruling 11)
}

export const unappliedId = (node: string, kind: UnappliedKind, pointer: string): string => `${idKey(node)}|${kind}|${pointer}`;

/** The edits of a step at a part and below it: what a change to that part applies first. "" is the whole step. */
export const within = (node: string, pointer: string) => (u: Unapplied): boolean =>
  sameId(u.node, node) && (pointer === "" || u.pointer === pointer || u.pointer.startsWith(`${pointer}/`));

export const STALE = "Not applied: what's here changed since this was typed (an undo, another edit). Apply it here, or discard it.";

/** What an edit is typed over, as JSON: the value at its place (a `literal` envelope included, so its kind counts),
 * a port's or the key's name, a limit; for an entry's name, whether the entry is still there. Its place is a pointer,
 * and an undo can put another item there: an edit is applied only where its base still is (the review of revision 3). */
export function baseOf(doc: GraphDoc, u: Pick<Unapplied, "node" | "kind" | "path" | "from">): string {
  const node = findNode(doc, u.node);
  if (!node) return "gone";
  if (u.kind === "key") return JSON.stringify(node.key);
  if (u.kind === "limit") return JSON.stringify(node.options?.[u.path[0] as Limit]) ?? "undefined";
  const at = valueAt(node.config ?? {}, u.path);
  if (u.kind === "name") return JSON.stringify(isObject(at) && Object.hasOwn(at, u.from ?? ""));
  return JSON.stringify(at) ?? "undefined";
}

/** The lists and items an edit's path runs through, as their roots (`rootOf`): for each list, the list's and the
 * item's. Equal values in two items, or a list rebuilt by a move, give other roots (the review of revision 4); an edit
 * in place beside it, which keeps them, doesn't. Maps are keyed by name, so they aren't part of it. */
export function lineageOf(doc: GraphDoc, u: Pick<Unapplied, "node" | "path">): unknown[] {
  const node = findNode(doc, u.node);
  const out: unknown[] = [];
  let at: unknown = node?.config ?? {};
  for (const key of u.path) {
    if (typeof key === "number" && Array.isArray(at)) {
      const item = (at as unknown[])[key];
      out.push(rootOf(at), typeof item === "object" && item !== null ? rootOf(item) : null);
      at = item;
    } else at = isObject(at) ? at[String(key)] : undefined;
  }
  return out;
}

/** Whether what an edit was typed over has changed, or moved: it's then applied only when the person says so (Apply
 * here). */
export const isStale = (doc: GraphDoc, u: Unapplied): boolean =>
  baseOf(doc, u) !== u.base || lineageOf(doc, u).some((root, i) => root !== u.lineage[i]) || lineageOf(doc, u).length !== u.lineage.length;

/** A number typed (rulings 7 and 18). What the draft keeps must be what was typed: never an infinity, never a whole
 * number past 2^53, in whatever notation, which Number() rounds. Empty text is no value. */
export function parseNumber(text: string, whole: boolean): { value: number | undefined } | { problem: string } {
  const t = text.trim();
  if (t === "") return { value: undefined };
  const n = Number(t);
  if (Number.isNaN(n) || (whole && Number.isFinite(n) && !Number.isInteger(n))) {
    return { problem: whole ? "A whole number, like 42." : "A number, like 42 or 2.5." };
  }
  if (!Number.isFinite(n)) return { problem: "A number this large can't be kept." };
  if (Number.isInteger(n) && !Number.isSafeInteger(n)) return { problem: "A whole number this large can't be kept exactly." };
  return { value: n };
}

/** The graph's bounds on a step's own limits (engine/graph/model.py's Options): a draft breaking one isn't saved. */
const LIMITS = {
  max_attempts: { ok: (n: number) => Number.isInteger(n) && n >= 1 && n <= 20, problem: "A whole number from 1 to 20." },
  timeout_s: { ok: (n: number) => n > 0 && n <= 86_400, problem: "A number of seconds above 0, up to 86,400." },
} as const;
export type Limit = keyof typeof LIMITS;

/** Why a limit's text isn't one the graph takes, or null: empty text leaves it to the type's default. */
export function limitProblem(name: Limit, text: string): string | null {
  const parsed = parseNumber(text, false);
  if ("problem" in parsed) return LIMITS[name].problem;
  return parsed.value === undefined || LIMITS[name].ok(parsed.value) ? null : LIMITS[name].problem;
}

/** A typed value as the draft writes it: emptied, it goes, or blanks in a list or a map; a literal's payload is wrapped
 * again (ruling 15). */
function written(value: unknown, u: Unapplied): unknown {
  if (value === undefined) return u.entry ? null : undefined;
  return u.literal ? literal(value) : value;
}

const quiet = (changed: Changed | { problem: string }): Applied | { problem: string } =>
  "problem" in changed ? changed : { ...changed, said: null, note: null };

function attempt(doc: GraphDoc, node: GraphNode, u: Unapplied, type: NodeType | undefined): Applied | { problem: string } {
  switch (u.kind) {
    case "text": // emptied, a property goes, and a list's or a map's text blanks to ""
      return quiet(setConfig(doc, u.node, u.path, u.text === "" ? (u.entry ? "" : undefined) : written(u.text, u), type));
    case "json": {
      const parsed = parseJson(u.text);
      return "problem" in parsed ? parsed : quiet(setConfig(doc, u.node, u.path, written(parsed.value, u), type));
    }
    case "number": {
      const parsed = parseNumber(u.text, u.whole ?? false);
      return "problem" in parsed ? parsed : quiet(setConfig(doc, u.node, u.path, written(parsed.value, u), type));
    }
    case "formula":
      return quiet(setConfig(doc, u.node, u.path, u.text.trim() === "" ? written(undefined, u) : formula(u.text), type));
    case "port": {
      if (!type) return { problem: "This step's type isn't on this server." };
      const name = u.text.trim();
      const renamed = renamePort(doc, u.node, u.path[1] as number, name, type);
      if ("problem" in renamed) return renamed;
      return { doc: renamed.doc, dropped: [], said: `The port is now ${name}; its edges follow it.`, note: null };
    }
    case "name": {
      const renamed = renameEntry(doc, u.node, u.path, u.from ?? "", u.text.trim());
      return "problem" in renamed ? renamed : { doc: renamed.doc, dropped: [], said: null, note: null };
    }
    case "key": {
      const key = u.text.trim();
      const problem = keyProblem(doc, u.node, key);
      if (problem) return { problem };
      const { doc: next, mentions } = renameKey(doc, u.node, key);
      // A mention, not a reference: CEL isn't parsed here (ruling 11).
      const note =
        mentions === 0 ? null
        : mentions === 1 ? `1 formula mentions ${node.key} and keeps its text: check it.`
        : `${mentions} formulas mention ${node.key} and keep their text: check them.`;  // prettier-ignore
      return { doc: next, dropped: [], said: `Renamed ${node.key} to ${key}.${note ? ` ${note}` : ""}`, note };
    }
    case "limit": {
      const name = u.path[0] as Limit;
      const problem = limitProblem(name, u.text);
      if (problem !== null) return { problem };
      const value = u.text.trim() === "" ? undefined : Number(u.text.trim());
      return quiet(setOptions(doc, u.node, { ...(node.options ?? {}), [name]: value }, type));
    }
  }
}

/** The draft with the edit applied, or why it can't be: its own rule, or the graph's admission (ruling 7). */
export function applyUnapplied(doc: GraphDoc, u: Unapplied, type: NodeType | undefined): Applied | { problem: string } {
  const node = findNode(doc, u.node);
  if (!node) return { problem: "Its step is no longer in the draft." };
  if (isStale(doc, u)) return { problem: STALE };
  const result = attempt(doc, node, u, type);
  if ("problem" in result) return result;
  const refused = admission(result.doc);
  return refused === null ? result : { problem: refused };
}

/** Why an edit that takes ports away waits for its question (ruling 9). */
export function droppedWhy(dropped: GraphEdge[], doc: GraphDoc): string {
  const ports = [...new Set(dropped.map(portOf))];
  const targets = [...new Set(dropped.map((e) => findNode(doc, e.to.node)?.key ?? "a step"))];
  return `Not applied: it removes ${ports.length === 1 ? "the port" : "the ports"} ${ports.join(", ")} and ${
    dropped.length === 1 ? "its edge" : "their edges"} to ${targets.join(", ")}.`;  // prettier-ignore
}

/** The order edits apply in, whatever order they were typed in: values before names, the deepest first, so a value is
 * written where it sits before its entry's rename moves it (the review of revision 2). */
const rank = (u: Unapplied): [number, number] => [u.kind === "name" ? 1 : 0, -u.pointer.split("/").length];
const byRank = (a: Unapplied, b: Unapplied) => {
  const [x, y] = [rank(a), rank(b)];
  return x[0] - y[0] || x[1] - y[1];
};

/** Each held edit `take` covers, applied in turn to one document, in rank order: what they make, those applied, and
 * those that stay with their reasons. One that takes ports away stays: that is asked one edit at a time (ruling 9). A
 * name stays while an edit inside its entry does: renamed, that edit would point at nothing. */
export function applyAll(
  doc: GraphDoc, held: Iterable<Unapplied>, typeOf: (node: GraphNode) => NodeType | undefined, take: (u: Unapplied) => boolean,
): { doc: GraphDoc; applied: Unapplied[]; left: Unapplied[]; note: string | null } {  // prettier-ignore
  let next = doc;
  let note: string | null = null;
  const applied: Unapplied[] = [];
  const left: Unapplied[] = [];
  for (const u of [...held].filter(take).sort(byRank)) {
    if (u.kind === "name" && left.some((v) => within(u.node, u.pointer)(v))) {
      left.push({ ...u, why: "Not applied: an edit inside it isn't applied yet." });
      continue;
    }
    const node = findNode(next, u.node);
    const result = applyUnapplied(next, u, node ? typeOf(node) : undefined);
    if ("problem" in result) left.push({ ...u, why: result.problem });
    else if (result.dropped.length > 0) left.push({ ...u, why: droppedWhy(result.dropped, next) });
    else {
      next = result.doc;
      note = result.note ?? note;
      applied.push(u);
    }
  }
  return { doc: next, applied, left, note };
}

/** Edits not applied, as a recovery file of their own (ruling 18): what was typed, and where. Never written into the
 * graph to keep it: the graph is what runs. */
export function unappliedFile(edits: Unapplied[], keyOf: (node: string) => string) {
  return {
    format: "dewpoint.unapplied-edits",
    edits: edits.map((u) => ({ step: keyOf(u.node), field: u.label, at: u.pointer, text: u.text, why: u.why })),
  };
}
