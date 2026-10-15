// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { GraphDoc } from "../../../lib/workflows";
import { bodyOf, cellOf, iterationOf } from "./loopBody";

const node = (key: string, type: string) => ({ id: `id-${key}`, key, type, config: {} });
const edge = (from: string, to: string, port?: string) => ({ from: { node: `id-${from}`, ...(port ? { port } : {}) }, to: { node: `id-${to}` } });
// each_ap loops over is_offline -> notify, and an inner loop over ping; report follows on done.
const DOC = {
  graph_format: 1,
  nodes: [node("each_ap", "flow.loop@1"), node("is_offline", "flow.if@1"), node("notify", "slack.post@1"), node("inner", "flow.loop@1"), node("ping", "testkit.echo@1"), node("report", "flow.transform@1")],
  edges: [edge("each_ap", "is_offline", "body"), edge("is_offline", "notify", "true"), edge("is_offline", "inner", "false"), edge("inner", "ping", "body"), edge("each_ap", "report", "done")],
} as unknown as GraphDoc;  // prettier-ignore

describe("a loop's iterations in the panel (§7.5; the ResultPanel board)", () => {
  it("lists the steps each iteration runs, in the draft's order: not a nested loop's own, nor what follows the loop", () => {
    expect(bodyOf(DOC, "id-each_ap").map((n) => n.key)).toEqual(["is_offline", "notify", "inner"]);
    expect(bodyOf(DOC, "id-inner").map((n) => n.key)).toEqual(["ping"]);
    expect(bodyOf(DOC, "id-report")).toEqual([]);
  });

  it("names an iteration as the engine keys it, under the loop's own", () => {
    expect(iterationOf("", "each_ap", 0)).toBe("each_ap:0");
    expect(iterationOf("outer:2", "each_ap", 3)).toBe("outer:2/each_ap:3");
  });

  it("words a step's instance in one iteration: the port it took, its status, a failure's code, a loop's count", () => {
    expect(cellOf({ status: "succeeded", effect: { port: "false" } }, "flow.if@1")).toEqual({ text: "→ false", failed: false, code: null });
    expect(cellOf({ status: "skipped", effect: null }, "slack.post@1")).toEqual({ text: "skipped", failed: false, code: null });
    expect(cellOf({ status: "failed", error: { code: "invalid_blocks", message: "Block 2 has no text." } }, "slack.post@1")).toEqual({ text: "failed", failed: true, code: "invalid_blocks" });
    expect(cellOf({ status: "succeeded", output: { items: [], failures: [], count: 3 } }, "flow.loop@1")).toEqual({ text: "3 iterations", failed: false, code: null });
    expect(cellOf({ status: "not_started" }, "slack.post@1")).toEqual({ text: "not started", failed: false, code: null });
    expect(cellOf(undefined, "slack.post@1")).toEqual({ text: "not recorded", failed: false, code: null });
  });
});
