// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { addsOf } from "./items";

const node = (id: string, type = "flow.transform@1") => ({ id, key: id, type, config: {} });

describe("a step's + in its panel", () => {
  it("offers an insert on every edge the canvas draws from the step, a port its type no longer lists included", () => {
    // An unknown or retired type lists no ports, and a switch's deleted case is gone from its type: their edges are
    // still drawn, each with its "+" (the final checkpoint's second review). Each needs its full-size twin.
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [node("x", "vendor.gone@1"), node("y")],
      edges: [{ from: { node: "x", port: "old" }, to: { node: "y" } }],
    };
    expect(addsOf(doc, doc.nodes![0]!, []).map((a) => a.label)).toEqual(["Insert a step before x", "Insert a step between x (old) and y"]);
  });

  it("lists the type's own ports first, then the others its edges leave from", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [node("s", "flow.switch@1"), node("a"), node("b")],
      edges: [{ from: { node: "s", port: "gone" }, to: { node: "a" } }, { from: { node: "s", port: "default" }, to: { node: "b" } }],
    };
    expect(addsOf(doc, doc.nodes![0]!, ["default", "c1"]).map((a) => a.label)).toEqual([
      "Insert a step before s",
      "Insert a step between s (default) and b",
      "Add a step after s (c1)",
      "Insert a step between s (gone) and a",
    ]);
  });
});
