// SPDX-License-Identifier: Apache-2.0
// The canvas's keyboard model (D16; 4b ruling 15, amended). Each item lists its children from the start card down:
// the start card, its edges to the entry steps, each step, each edge leaving it (by port, then left to right), each
// free port. A step joined from two places is a child of both, so the keys carry the path they came by (`step`): Up
// goes back that way, and Left and Right stay among the children of the item it came from. A step no entry reaches
// (a cycle no entry leads into, a step whose only edges in come from steps that aren't there) joins the start card's
// children, topmost first: every item the canvas draws is reached by the keys. Home goes to the start card. A
// read-only canvas (a viewer, a conflict, an old version) holds the start card and the steps only.
import { START, drawableEdges, entries, nodesOf, portOf, pos } from "../../lib/graph";
import type { GraphDoc, GraphEdge } from "../../lib/workflows";
import { item } from "./items";

export type NavKey = "ArrowDown" | "ArrowUp" | "ArrowLeft" | "ArrowRight" | "Home";
export const NAV_KEYS: readonly string[] = ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home"];

export interface Nav {
  children: Map<string, string[]>;
  parent: Map<string, string>;
  order: string[]; // every item, breadth first from the start card
  edges: Map<string, GraphEdge>; // an edge item's edge
}

export function navModel(doc: GraphDoc, portsOf: (nodeId: string) => string[], editable: boolean): Nav {
  const children = new Map<string, string[]>();
  const edges = new Map<string, GraphEdge>();
  const nodes = nodesOf(doc);
  const drawn = drawableEdges(doc);
  const x = new Map(nodes.map((n) => [n.id, pos(n).x]));
  const byPlace = (a: GraphEdge, b: GraphEdge) =>
    (x.get(a.to.node) ?? 0) - (x.get(b.to.node) ?? 0) || a.to.node.localeCompare(b.to.node);
  const first = [...entries(doc)].sort((a, b) => pos(a).x - pos(b).x || a.id.localeCompare(b.id));
  const top = editable ? first.map((n) => item.entry(n.id)) : first.map((n) => item.node(n.id));
  if (editable) for (const n of first) children.set(item.entry(n.id), [item.node(n.id)]);
  if (editable && nodes.length === 0) top.push(item.port(START, "out"));
  children.set(item.start, top);
  for (const n of nodes) {
    const leaving = drawn.filter((e) => e.from.node === n.id);
    const own = portsOf(n.id);
    const ports = [...own, ...new Set(leaving.map(portOf).filter((p) => !own.includes(p)))];
    const out: string[] = [];
    for (const port of ports) {
      const here = leaving.filter((e) => portOf(e) === port).sort(byPlace);
      if (!editable) {
        // Read only, a step's children are the steps it leads to, each once (two ports may lead to one step).
        for (const id of here.map((e) => item.node(e.to.node))) if (!out.includes(id)) out.push(id);
        continue;
      }
      for (const e of here) {
        const id = item.edge(e);
        edges.set(id, e);
        children.set(id, [item.node(e.to.node)]);
        out.push(id);
      }
      if (here.length === 0 && own.includes(port)) out.push(item.port(n.id, port));
    }
    children.set(item.node(n.id), out);
  }
  const parent = new Map<string, string>();
  const order: string[] = [];
  const seen = new Set<string>([item.start]);
  const queue = [item.start];
  const walk = () => {
    while (queue.length) {
      const at = queue.shift()!;
      order.push(at);
      for (const child of children.get(at) ?? []) {
        if (seen.has(child)) continue;
        seen.add(child);
        parent.set(child, at);
        queue.push(child);
      }
    }
  };
  walk();
  // A step the start card doesn't reach becomes one of its children (so Down, Left and Right get there), topmost
  // first, and what it reaches is walked from it; until every step is reached.
  const unreached = () =>
    nodes
      .filter((n) => !seen.has(item.node(n.id)))
      .sort((a, b) => pos(a).y - pos(b).y || pos(a).x - pos(b).x || a.id.localeCompare(b.id));
  for (let rest = unreached(); rest.length > 0; rest = unreached()) {
    const root = item.node(rest[0]!.id);
    top.push(root);
    seen.add(root);
    parent.set(root, item.start);
    queue.push(root);
    walk();
  }
  return { children, parent, order, edges };
}

/** Whether `path` runs from the start card, each item a child of the one before (still true after a change). */
export function isPath(nav: Nav, path: string[]): boolean {
  return path[0] === item.start && path.every((id, i) => i === 0 || (nav.children.get(path[i - 1]!) ?? []).includes(id));
}

/** The walk's own path to an item (its first parent at each step): where a click, Tab or a change leaves the keys. */
export function pathTo(nav: Nav, id: string): string[] {
  if (!nav.order.includes(id)) return [item.start];
  const path = [id];
  for (let at = nav.parent.get(id); at !== undefined; at = nav.parent.get(at)) path.unshift(at);
  return path;
}

/** One key, from the path the keys came by: Down to the first child, Up back the way it came, Left and Right among
 * the children of the item it came from (at a join, the branch it came by: the owner's review of revision 2), Home
 * to the start card. Down, Left and Right pass over items already on the path (a cycle's way back, a self edge), so
 * a path never repeats an item: it stays finite, and the walk's own path reaches every item (the revision's review). */
export function step(nav: Nav, path: string[], key: NavKey): string[] {
  if (key === "Home") return [item.start];
  const here = path.at(-1)!;
  if (key === "ArrowDown") {
    const child = (nav.children.get(here) ?? []).find((c) => !path.includes(c));
    return child === undefined ? path : [...path, child];
  }
  if (key === "ArrowUp") return path.length > 1 ? path.slice(0, -1) : path;
  if (path.length < 2) return path;
  const above = path.slice(0, -1);
  const siblings = nav.children.get(path.at(-2)!) ?? [];
  const by = key === "ArrowLeft" ? -1 : 1;
  for (let i = siblings.indexOf(here) + by; i >= 0 && i < siblings.length; i += by) {
    if (!above.includes(siblings[i]!)) return [...above, siblings[i]!];
  }
  return path;
}
