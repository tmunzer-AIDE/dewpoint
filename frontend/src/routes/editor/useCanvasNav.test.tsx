// SPDX-License-Identifier: Apache-2.0
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { useCanvasNav } from "./useCanvasNav";

const node = (id: string, x = 0) => ({ id, key: id, type: "flow.transform@1", position: { x, y: 0 } });
const edge = (from: string, to: string, port = "out") => ({ from: { node: from, port }, to: { node: to } });
// A branch whose two ways join again: `end` is reached from `yes` and from `no`.
const DOC: GraphDoc = {
  graph_format: 1,
  nodes: [node("if"), node("yes", 0), node("no", 300), node("end")],
  edges: [edge("if", "yes", "true"), edge("if", "no", "false"), edge("yes", "end"), edge("no", "end")],
};
const ports = (id: string) => (id === "if" ? ["true", "false"] : ["out"]);

it("walks a read-only canvas with the arrow keys from its one tab stop, back the way the keys came (D16)", () => {
  const { result } = renderHook(() => useCanvasNav(DOC, ports, false));
  expect(result.current.shown).toBe("start");
  for (const key of ["ArrowDown", "ArrowDown", "ArrowRight", "ArrowDown"] as const) act(() => result.current.walk(key));
  expect(result.current.shown).toBe("node:end");
  act(() => result.current.walk("ArrowUp"));
  expect(result.current.shown).toBe("node:no"); // the way it came, not the first way to it
  expect(result.current.focusRequest).toEqual({ id: "node:no", n: 5 });
});

it("takes the tab stop where focus went, and falls back to the start card when its item is gone", () => {
  const { result, rerender } = renderHook(({ doc }) => useCanvasNav(doc, ports, false), { initialProps: { doc: DOC } });
  act(() => result.current.onFocusItem("node:end"));
  expect(result.current.shown).toBe("node:end");
  rerender({ doc: { ...DOC, nodes: DOC.nodes!.filter((n) => n.id !== "end"), edges: DOC.edges!.filter((e) => e.to.node !== "end") } });
  expect(result.current.shown).toBe("start");
});
