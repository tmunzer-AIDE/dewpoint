// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { NAV_KEYS, isPath, navModel, pathTo, step, type Nav, type NavKey } from "./canvasNav";

const node = (id: string, x = 0) => ({ id, key: id, type: "flow.transform@1", position: { x, y: 0 } });
const edge = (from: string, to: string, port = "out") => ({ from: { node: from, port }, to: { node: to } });
const ports = (map: Record<string, string[]>) => (id: string) => map[id] ?? ["out"];
/** The item a path ends on: the focused one. */
const at = (path: string[]) => path.at(-1);
/** The path after pressing `keys` from `from`. */
const press = (nav: Nav, from: string[], ...keys: NavKey[]) => keys.reduce((path, key) => step(nav, path, key), from);

it("walks a chain down and back up, through its edges and its last free port", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b")] };
  const nav = navModel(doc, ports({}), true);
  const seen: (string | undefined)[] = [];
  let path = ["start"];
  for (let i = 0; i < 5; i++) seen.push(at((path = step(nav, path, "ArrowDown"))));
  expect(seen).toEqual(["entry:a", "node:a", "edge:a:out->b", "node:b", "port:b:out"]);
  expect(at(press(nav, path, "ArrowDown"))).toBe("port:b:out");
  expect(at(press(nav, pathTo(nav, "node:b"), "ArrowUp"))).toBe("edge:a:out->b");
  expect(press(nav, path, "Home")).toEqual(["start"]);
});

it("moves across a branch's ports, left to right, an empty port included", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("if"), node("yes")], edges: [edge("if", "yes", "true")] };
  const nav = navModel(doc, ports({ if: ["true", "false"] }), true);
  expect(nav.children.get("node:if")).toEqual(["edge:if:true->yes", "port:if:false"]);
  const onTrue = pathTo(nav, "edge:if:true->yes");
  expect(at(press(nav, onTrue, "ArrowRight"))).toBe("port:if:false");
  expect(at(press(nav, onTrue, "ArrowRight", "ArrowRight"))).toBe("port:if:false");
  expect(at(press(nav, onTrue, "ArrowRight", "ArrowLeft"))).toBe("edge:if:true->yes");
});

it("orders a port's targets by where they sit, and keeps an edge from a port the type no longer has", () => {
  const doc: GraphDoc = {
    graph_format: 1,
    nodes: [node("a"), node("right", 300), node("left", 0), node("odd", 600)],
    edges: [edge("a", "right"), edge("a", "left"), edge("a", "odd", "gone")],
  };  // prettier-ignore
  const nav = navModel(doc, ports({}), true);
  expect(nav.children.get("node:a")).toEqual(["edge:a:out->left", "edge:a:out->right", "edge:a:gone->odd"]);
});

it("reads a read-only canvas step to step, with nothing to add", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b")] };
  const nav = navModel(doc, ports({}), false);
  expect(nav.order).toEqual(["start", "node:a", "node:b"]);
});

it("offers the start card's own '+' before any step, and links a cycle no entry reaches under it", () => {
  expect(navModel({ graph_format: 1, nodes: [], edges: [] }, ports({}), true).order).toEqual(["start", "port:start:out"]);
  const loop: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] };
  const nav = navModel(loop, ports({}), false);
  expect(nav.children.get("start")).toEqual(["node:a"]);
  expect(press(nav, ["start"], "ArrowDown", "ArrowDown")).toEqual(["start", "node:a", "node:b"]);
  // Down from b finds only a, already on the path: it stays, and the path never grows round the cycle.
  expect(press(nav, ["start"], "ArrowDown", "ArrowDown", "ArrowDown")).toEqual(["start", "node:a", "node:b"]);
});

// a → b, c; b → d, e; c → d, f: d is reached from b and from c (the owner's review of revision 2).
const JOINS: GraphDoc = {
  graph_format: 1,
  nodes: [node("a"), node("b"), node("c", 300), node("d"), node("e", 300), node("f", 600)],
  edges: [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("b", "e"), edge("c", "d"), edge("c", "f")],
};  // prettier-ignore

it("keeps to the branch it came by at a join: from d reached through c, the sibling is f", () => {
  const readOnly = navModel(JOINS, ports({}), false); // c's children are the steps d and f
  const toD = press(readOnly, pathTo(readOnly, "node:c"), "ArrowDown");
  expect(at(toD)).toBe("node:d");
  expect(at(press(readOnly, toD, "ArrowRight"))).toBe("node:f"); // never b's e
  expect(at(press(readOnly, toD, "ArrowUp"))).toBe("node:c"); // back the way it came, never to b
  const editable = navModel(JOINS, ports({}), true); // c's children are the edges c→d and c→f
  const viaEdge = press(editable, pathTo(editable, "node:c"), "ArrowDown", "ArrowDown");
  expect(at(viaEdge)).toBe("node:d");
  expect(at(press(editable, viaEdge, "ArrowUp"))).toBe("edge:c:out->d");
  expect(at(press(editable, viaEdge, "ArrowUp", "ArrowRight", "ArrowDown"))).toBe("node:f");
});

it("takes a path only while each of its steps is a child of the one before", () => {
  const nav = navModel(JOINS, ports({}), false);
  expect(isPath(nav, ["start", "node:a", "node:c", "node:d"])).toBe(true);
  expect(isPath(nav, ["start", "node:a", "node:e"])).toBe(false);
  expect(pathTo(nav, "node:gone")).toEqual(["start"]);
});

/** Every item the canvas draws for `doc`, counted from the document itself, never from the model under test. */
function drawnItems(doc: GraphDoc, portsOf: (id: string) => string[], editable: boolean): Set<string> {
  const nodes = doc.nodes ?? [];
  const out = new Set<string>(["start", ...nodes.map((n) => `node:${n.id}`)]);
  if (!editable) return out;
  if (nodes.length === 0) out.add("port:start:out");
  const ids = new Set(nodes.map((n) => n.id));
  const targets = new Set((doc.edges ?? []).map((e) => e.to.node));
  for (const n of nodes) if (!targets.has(n.id)) out.add(`entry:${n.id}`);
  const drawn = (doc.edges ?? []).filter((e) => ids.has(e.from.node) && ids.has(e.to.node));
  for (const e of drawn) out.add(`edge:${e.from.node}:${e.from.port ?? "out"}->${e.to.node}`);
  for (const n of nodes) {
    for (const p of portsOf(n.id)) {
      if (!drawn.some((e) => e.from.node === n.id && (e.from.port ?? "out") === p)) out.add(`port:${n.id}:${p}`);
    }
  }
  return out;
}

/** Every item the keys reach from the start card: each key pressed from each path reached, the path carried along,
 * as the editor carries it. */
function reachedByKeys(nav: Nav): Set<string> {
  const reached = new Set(["start"]);
  const seen = new Set([JSON.stringify(["start"])]);
  const todo = [["start"]];
  while (todo.length) {
    const path = todo.pop()!;
    for (const key of NAV_KEYS as NavKey[]) {
      const next = step(nav, path, key);
      const id = JSON.stringify(next);
      if (seen.has(id)) continue;
      seen.add(id);
      reached.add(at(next)!);
      todo.push(next);
    }
  }
  return reached;
}

const CASES: [string, GraphDoc, Record<string, string[]>][] = [
  ["a chain", { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b")] }, {}],
  [
    "a branch and its join",
    { graph_format: 1, nodes: [node("if"), node("y"), node("n", 300), node("j")],
      edges: [edge("if", "y", "true"), edge("if", "n", "false"), edge("y", "j"), edge("n", "j")] },
    { if: ["true", "false"] },
  ],
  ["a join a second branch also reaches", JOINS, {}],
  ["a cycle no entry leads into", { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] }, {}],
  ["a cycle beside an entry", { graph_format: 1, nodes: [node("e"), node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] }, {}],
  [
    "two components, one looping back into its chain",
    { graph_format: 1, nodes: [node("a"), node("b"), node("c"), node("x"), node("y")],
      edges: [edge("a", "b"), edge("b", "c"), edge("c", "b"), edge("x", "y"), edge("y", "x")] },
    {},
  ],
  [
    "an imported draft's dangling, repeated and self edges",
    { graph_format: 1, nodes: [node("a"), node("b")],
      edges: [edge("a", "b"), edge("a", "b"), edge("gone", "b"), edge("a", "gone"), edge("b", "b")] },
    {},
  ],
  [
    "a step of an unknown type, reached from a port its source's type lacks",
    { graph_format: 1, nodes: [node("a"), node("odd")], edges: [edge("a", "odd", "gone")] },
    { odd: [] },
  ],
  // The revision's review: graphs on which revision 3's first `step` stranded a step, or grew the path without end.
  [
    "a cycle's way back beside a branch",
    { graph_format: 1, nodes: [node("s"), node("a"), node("b"), node("c", 300)],
      edges: [edge("s", "a"), edge("a", "b"), edge("b", "a"), edge("b", "c")] },
    {},
  ],
  [
    "a self edge beside a branch",
    { graph_format: 1, nodes: [node("s"), node("a"), node("b", 300)], edges: [edge("s", "a"), edge("a", "a"), edge("a", "b")] },
    {},
  ],
  [
    "two ports to one step, a third to another",
    { graph_format: 1, nodes: [node("if"), node("b"), node("c", 300)],
      edges: [edge("if", "b", "true"), edge("if", "b", "false"), edge("if", "c", "error")] },
    { if: ["true", "false", "error"] },
  ],
  [
    "a self edge, and a step left of it",
    { graph_format: 1, nodes: [node("s"), node("a", 300), node("b"), node("c")],
      edges: [edge("s", "a"), edge("a", "b"), edge("a", "a"), edge("b", "c")] },
    {},
  ],
];  // prettier-ignore

// Read only is how a viewer, an editor after a conflict, and any viewed version see the canvas: all three hand
// `navModel` `editable: false`.
it.each(CASES)("reaches every item of %s with the keys alone, editable or read only", (_, doc, map) => {
  for (const editable of [true, false]) {
    expect(reachedByKeys(navModel(doc, ports(map), editable))).toEqual(drawnItems(doc, ports(map), editable));
  }
});
