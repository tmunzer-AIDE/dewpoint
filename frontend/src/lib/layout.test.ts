// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { ROW } from "./graph";
import { CARD, MIN_ZOOM, layout } from "./layout";
import type { GraphDoc } from "./workflows";

const n = (id: string) => ({ id, key: id, type: "flow.transform@1", position: { x: 900, y: 900 } });
const e = (from: string, to: string, port = "out") => ({ from: { node: from, port }, to: { node: to } });

it("lays a chain out top to bottom, a row apart, below the start card", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [n("a"), n("b"), n("c")], edges: [e("a", "b"), e("b", "c")] };
  const at = layout(doc);
  expect([at.get("a")!.y, at.get("b")!.y, at.get("c")!.y]).toEqual([ROW, 2 * ROW, 3 * ROW]);
  expect(new Set([at.get("a")!.x, at.get("b")!.x, at.get("c")!.x]).size).toBe(1);
});

it("puts a branch's two sides on one row, apart", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [n("if"), n("yes"), n("no")], edges: [e("if", "yes", "true"), e("if", "no", "false")] };
  const at = layout(doc);
  expect(at.get("yes")!.y).toBe(at.get("no")!.y);
  expect(Math.abs(at.get("yes")!.x - at.get("no")!.x)).toBeGreaterThanOrEqual(260);
});

it("places every step, ignores an edge to a missing one, and gives the same answer twice", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [n("a"), n("lonely")], edges: [e("a", "ghost")] };
  expect([...layout(doc).keys()].sort()).toEqual(["a", "lonely"]);
  expect([...layout(doc)]).toEqual([...layout(doc)]);
});

it("follows an edge whose ends are spelt otherwise than the steps", () => {
  const A = "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e0a";
  const B = "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e0b";
  const doc: GraphDoc = { graph_format: 1, nodes: [n(A), n(B)], edges: [e(A.toUpperCase(), B.replace(/-/g, ""))] };
  const at = layout(doc);
  expect([at.get(A)!.y, at.get(B)!.y]).toEqual([ROW, 2 * ROW]);
});

it("never zooms out past where a card stays a 24 px target (WCAG 2.5.8; the owner's ruling on M26)", () => {
  // The canvas bounds every way of zooming (wheel, pinch, its buttons, Fit) by MIN_ZOOM: a card, the start card
  // included, is then at least 24 by 24 on the screen.
  expect(CARD.height * MIN_ZOOM).toBeGreaterThanOrEqual(24);
  expect(CARD.width * MIN_ZOOM).toBeGreaterThanOrEqual(24);
});
