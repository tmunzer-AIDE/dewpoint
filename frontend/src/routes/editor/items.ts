// SPDX-License-Identifier: Apache-2.0
// The canvas's items: what its one roving tab stop moves among (4b ruling 15), and what each action targets.
import { START, drawableEdges, edgeId, entries, findNode, idKey, portOf, sameId, type PortRef } from "../../lib/graph";
import type { GraphDoc, GraphEdge, GraphNode } from "../../lib/workflows";

// A step's items are named by its id's identity (`idKey`), so two spellings of one step are one item.
export const item = {
  start: START,
  node: (id: string) => `node:${idKey(id)}`,
  edge: (edge: GraphEdge) => `edge:${edgeId(edge)}`,
  entry: (id: string) => `entry:${idKey(id)}`,
  port: (node: string, port: string) => `port:${idKey(node)}:${port}`,
};

export type ItemAction =
  | { kind: "open"; node: string }
  | { kind: "after"; from: PortRef | null }
  | { kind: "insert"; edge: GraphEdge }
  | { kind: "before"; entry: string };

/** What each "+" says, on the canvas and in a step's panel alike: a port is named when it isn't `out`. */
const named = (key: string, port: string) => `${key}${port === "out" ? "" : ` (${port})`}`;
export const say = {
  after: (key: string, port: string) => `Add a step after ${named(key, port)}`,
  insert: (from: string, port: string, to: string) => `Insert a step between ${named(from, port)} and ${to}`,
  before: (key: string) => `Insert a step before ${key}`,
};

/** Every "+" a step has on the canvas, in the canvas's words: before it when it's an entry, then per port, an insert
 * on each edge it leads by, or an add after it when it leads nowhere. Its panel offers them unscaled: the canvas's
 * "+" scale with the zoom, and these are their full-size equivalents (WCAG 2.5.8; the owner's ruling on M26). */
export function addsOf(doc: GraphDoc, node: GraphNode, ports: string[]): { label: string; action: ItemAction }[] {
  const keyOf = (id: string) => findNode(doc, id)?.key ?? "a step";
  const out: { label: string; action: ItemAction }[] = [];
  if (entries(doc).some((n) => sameId(n.id, node.id))) out.push({ label: say.before(node.key), action: { kind: "before", entry: node.id } });
  const edges = drawableEdges(doc).filter((e) => sameId(e.from.node, node.id));
  for (const port of ports) {
    const leads = edges.filter((e) => portOf(e) === port);
    if (leads.length === 0) out.push({ label: say.after(node.key, port), action: { kind: "after", from: { node: node.id, port } } });
    for (const e of leads) out.push({ label: say.insert(node.key, port, keyOf(e.to.node)), action: { kind: "insert", edge: e } });
  }
  return out;
}
