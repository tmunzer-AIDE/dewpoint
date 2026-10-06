// SPDX-License-Identifier: Apache-2.0
// The draft as a document, and every change the editor makes to it, as pure functions (4b). Each returns a new
// document and keeps what it doesn't touch as it was, byte for byte: a draft from elsewhere (an import, an unknown
// node type, a settings block) round-trips. The server checks everything; nothing here validates.
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

export const START = "start"; // the start card on the canvas: never a node's id (those are UUIDs)
export const ROW = 140; // from one step's top to the next one's: a 64 px card and its gap
export const COLUMN = 300; // from one sibling's left to the next one's: a 260 px card and its gap
const KEY = /^[a-z][a-z0-9_]{0,62}$/;

export interface PortRef {
  node: string;
  port: string;
}

/** A draft from the API, as a document: it was format-checked when saved (4b ruling 9). */
export const asGraph = (draft: unknown): GraphDoc => draft as GraphDoc;
export const nodesOf = (doc: GraphDoc): GraphNode[] => doc.nodes ?? [];
export const edgesOf = (doc: GraphDoc): GraphEdge[] => doc.edges ?? [];
export const portOf = (edge: GraphEdge): string => edge.from.port ?? "out";

/** An edge's identity on the canvas: the graph gives edges no id. */
export const edgeId = (edge: GraphEdge): string => `${edge.from.node}:${portOf(edge)}->${edge.to.node}`;

export const pos = (node: GraphNode): { x: number; y: number } => ({ x: node.position?.x ?? 0, y: node.position?.y ?? 0 });

/** A step's ports, in the canvas's order: one per entry of its type's dynamic field (in the config's order), then
 * the type's own, then `error` when the step routes its errors there. A type the palette doesn't know has none. */
export function portsOf(node: GraphNode, type: NodeType | undefined): string[] {
  const ports: string[] = [];
  const add = (port: unknown) => typeof port === "string" && !ports.includes(port) && ports.push(port);
  if (type?.dynamic_ports) {
    const entries = (node.config ?? {})[type.dynamic_ports];
    if (Array.isArray(entries)) for (const entry of entries) add((entry as { port?: unknown } | null)?.port);
  }
  for (const port of type?.ports ?? []) add(port);
  if (node.options?.on_error === "port") add("error");
  return ports;
}

/** The port that carries the flow on when a step goes mid-edge (4b ruling 10): `out`, or a loop's `done`. */
export function continuationPort(type: NodeType): string | null {
  if (type.ports.includes("out")) return "out";
  if (type.ports.includes("done")) return "done";
  return null;
}

/** A key from the type's last name segment (`flow.transform` → `transform`), numbered when taken. */
export function keyFor(type: NodeType, taken: Iterable<string>): string {
  const used = new Set(taken);
  let base = (type.type.split(".").pop() ?? "").toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "").slice(0, 56);
  if (!KEY.test(base)) base = "step";
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) if (!used.has(`${base}_${n}`)) return `${base}_${n}`;
}

/** The config's top-level defaults from the type's schema; a connection field gets none (4b ruling 11). */
export function defaultConfig(type: NodeType): Record<string, unknown> {
  const properties = (type.config_schema as { properties?: Record<string, Record<string, unknown>> }).properties ?? {};
  const config: Record<string, unknown> = {};
  for (const [name, spec] of Object.entries(properties)) {
    if ("default" in spec && !spec["x-dewpoint-connection"]) config[name] = structuredClone(spec.default);
  }
  return config;
}

function newNode(type: NodeType, doc: GraphDoc, at: { x: number; y: number }, id: string): GraphNode {
  return {
    id,
    key: keyFor(type, nodesOf(doc).map((n) => n.key)),
    type: type.ref,
    config: defaultConfig(type),
    position: { x: Math.round(at.x), y: Math.round(at.y) },
  };
}

/** Steps no edge leads to: where a run starts. */
export function entries(doc: GraphDoc): GraphNode[] {
  const targets = new Set(edgesOf(doc).map((e) => e.to.node));
  return nodesOf(doc).filter((n) => !targets.has(n.id));
}

/** The start card: a row above the entry steps (or all steps, when a cycle leaves none), at their left. */
export function startPosition(doc: GraphDoc): { x: number; y: number } {
  const first = entries(doc).length ? entries(doc) : nodesOf(doc);
  if (first.length === 0) return { x: 0, y: 0 };
  return { x: Math.min(...first.map((n) => pos(n).x)), y: Math.min(...first.map((n) => pos(n).y)) - ROW };
}

const findNode = (doc: GraphDoc, id: string) => nodesOf(doc).find((n) => n.id === id);
const newId = () => crypto.randomUUID();

/** A step after a port, below its source and right of the port's other targets; or, from the start card (`null`),
 * a new entry step beside the others. */
export function addAfter(doc: GraphDoc, from: PortRef | null, type: NodeType, id: string = newId()) {
  const source = from ? findNode(doc, from.node) : undefined;
  const base = source ? pos(source) : startPosition(doc);
  const beside = from ? edgesOf(doc).filter((e) => e.from.node === from.node).length : entries(doc).length;
  const node = newNode(type, doc, { x: base.x + beside * COLUMN, y: base.y + ROW }, id);
  const edges = from ? [...edgesOf(doc), { from: { node: from.node, port: from.port }, to: { node: node.id } }] : edgesOf(doc);
  return { doc: { ...doc, nodes: [...nodesOf(doc), node], edges }, node };
}

/** Every step at or below `y` moves down a row: room for a step inserted there. */
function makeRoom(doc: GraphDoc, y: number): GraphNode[] {
  return nodesOf(doc).map((n) => (pos(n).y >= y ? { ...n, position: { ...pos(n), y: pos(n).y + ROW } } : n));
}

/** A step mid-edge: the edge now reaches it, and its continuation port reaches the old target (4b ruling 10). */
export function insertOnEdge(doc: GraphDoc, edge: GraphEdge, type: NodeType, id: string = newId()) {
  const port = continuationPort(type);
  if (!port) return null;
  const source = findNode(doc, edge.from.node);
  const target = findNode(doc, edge.to.node);
  const y = (source ? pos(source).y : startPosition(doc).y) + ROW;
  const node = newNode(type, doc, { x: target ? pos(target).x : source ? pos(source).x : 0, y }, id);
  const edges = edgesOf(doc).filter((e) => edgeId(e) !== edgeId(edge));
  edges.push({ from: edge.from, to: { node: node.id } }, { from: { node: node.id, port }, to: edge.to });
  return { doc: { ...doc, nodes: [...makeRoom(doc, y), node], edges }, node };
}

/** A step between the start card and an entry step, which it now leads to. */
export function insertBeforeEntry(doc: GraphDoc, entryId: string, type: NodeType, id: string = newId()) {
  const port = continuationPort(type);
  const entry = findNode(doc, entryId);
  if (!port || !entry) return null;
  const at = pos(entry);
  const node = newNode(type, doc, at, id);
  return {
    doc: { ...doc, nodes: [...makeRoom(doc, at.y), node], edges: [...edgesOf(doc), { from: { node: node.id, port }, to: { node: entryId } }] },
    node,
  };
}

/** A step removed with its edges and its declassify entries; with exactly one edge in and one out, its predecessor
 * now leads to its successor (`healed`, 4b ruling 12). References to it elsewhere stay: the validator reports them. */
export function deleteNode(doc: GraphDoc, id: string): { doc: GraphDoc; healed: GraphEdge | null } {
  const inbound = edgesOf(doc).filter((e) => e.to.node === id);
  const outbound = edgesOf(doc).filter((e) => e.from.node === id);
  const edges = edgesOf(doc).filter((e) => e.to.node !== id && e.from.node !== id);
  let healed: GraphEdge | null = null;
  if (inbound.length === 1 && outbound.length === 1) {
    const candidate = { from: inbound[0]!.from, to: outbound[0]!.to };
    if (candidate.to.node !== candidate.from.node && !edges.some((e) => edgeId(e) === edgeId(candidate))) {
      healed = candidate;
      edges.push(candidate);
    }
  }
  const settings = doc.settings?.declassify
    ? { ...doc.settings, declassify: doc.settings.declassify.filter((d) => d.node !== id) }
    : doc.settings;
  return { doc: { ...doc, nodes: nodesOf(doc).filter((n) => n.id !== id), edges, ...(settings ? { settings } : {}) }, healed };
}

export function deleteEdge(doc: GraphDoc, edge: GraphEdge): GraphDoc {
  return { ...doc, edges: edgesOf(doc).filter((e) => edgeId(e) !== edgeId(edge)) };
}

/** Whether `to` is reachable from `from` along edges. */
export function reaches(doc: GraphDoc, from: string, to: string): boolean {
  const next = new Map<string, string[]>();
  for (const e of edgesOf(doc)) next.set(e.from.node, [...(next.get(e.from.node) ?? []), e.to.node]);
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const at = stack.pop()!;
    if (at === to) return true;
    if (seen.has(at)) continue;
    seen.add(at);
    stack.push(...(next.get(at) ?? []));
  }
  return false;
}

/** A new edge from a port to a step: never to itself, never twice, never closing a cycle (4b ruling 14). */
export function canConnect(doc: GraphDoc, from: PortRef, to: string): boolean {
  if (from.node === to || !findNode(doc, to)) return false;
  if (edgesOf(doc).some((e) => e.from.node === from.node && portOf(e) === from.port && e.to.node === to)) return false;
  return !reaches(doc, to, from.node);
}

export function connect(doc: GraphDoc, from: PortRef, to: string): GraphDoc | null {
  if (!canConnect(doc, from, to)) return null;
  return { ...doc, edges: [...edgesOf(doc), { from: { node: from.node, port: from.port }, to: { node: to } }] };
}

/** The edges the canvas draws and the keyboard walks: both ends exist, each once. An imported draft may hold an edge
 * to a step that isn't there, or the same edge twice; the validator reports them, and nothing draws them. */
export function drawableEdges(doc: GraphDoc): GraphEdge[] {
  const ids = new Set(nodesOf(doc).map((n) => n.id));
  const seen = new Set<string>();
  return edgesOf(doc).filter((e) => {
    const id = edgeId(e);
    if (!ids.has(e.from.node) || !ids.has(e.to.node) || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

/** Steps moved to whole-pixel positions; every other step is the same object as before. */
export function moveNodes(doc: GraphDoc, positions: Map<string, { x: number; y: number }>): GraphDoc {
  return {
    ...doc,
    nodes: nodesOf(doc).map((n) => {
      const p = positions.get(n.id);
      return p ? { ...n, position: { x: Math.round(p.x), y: Math.round(p.y) } } : n;
    }),
  };
}
