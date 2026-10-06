// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import {
  ROW, addAfter, canConnect, connect, continuationPort, defaultConfig, deleteEdge, deleteNode, drawableEdges, edgeId,
  entries, insertBeforeEntry, insertOnEdge, keyFor, moveNodes, portsOf, startPosition,
} from "./graph";  // prettier-ignore
import type { GraphDoc, NodeType } from "./workflows";

const type = (ref: string, ports: string[], extra: Partial<NodeType> = {}): NodeType => ({
  ref, type: ref.split("@")[0]!, version: 1, kind: "control", state: "active", title: ref, description: "", icon: null,
  ports, dynamic_ports: null, config_schema: {}, output_schema: {}, options: [], side_effect: "none", credentials: [],
  capabilities: [], retry: { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] },
  timeout_s: 60, ...extra,
});  // prettier-ignore
const TRANSFORM = type("flow.transform@1", ["out"], {
  config_schema: { properties: { fields: { type: "object", default: {} }, connection: { type: "string", "x-dewpoint-connection": "mist", default: "x" } } },
});  // prettier-ignore
const IF = type("flow.if@1", ["true", "false"]);
const LOOP = type("flow.loop@1", ["body", "done"]);
const STOP = type("flow.stop@1", []);
const SWITCH = type("flow.switch@1", ["default"], { dynamic_ports: "cases" });

// a → b, with what the editor doesn't model kept around them
const doc = (): GraphDoc => ({
  graph_format: 1,
  nodes: [
    { id: "a", key: "a", type: "flow.transform@1", config: { fields: { x: 1 } }, position: { x: 0, y: 0 }, options: { timeout_s: 30 } },
    { id: "b", key: "b", type: "vendor.unknown@3", config: { secret_looking: "kept" }, position: { x: 0, y: 140 } },
  ],
  edges: [{ from: { node: "a", port: "out" }, to: { node: "b" } }],
  settings: { input_schema: { type: "object" }, declassify: [{ node: "b", field: "/x" }] },
});  // prettier-ignore

describe("ports", () => {
  it("lists a dynamic port per config entry, then the type's own, then error when errors route there", () => {
    const node = { id: "s", key: "s", type: "flow.switch@1", config: { cases: [{ port: "eu" }, { port: "us" }] }, options: { on_error: "port" as const } };
    expect(portsOf(node, SWITCH)).toEqual(["eu", "us", "default", "error"]);
    expect(portsOf({ id: "u", key: "u", type: "vendor.unknown@3" }, undefined)).toEqual([]);
  });

  it("continues an inserted step through out, or a loop's done, and never through a branch", () => {
    expect([continuationPort(TRANSFORM), continuationPort(LOOP), continuationPort(IF), continuationPort(STOP)]).toEqual([
      "out", "done", null, null,
    ]);  // prettier-ignore
  });
});

describe("a new step", () => {
  it("takes a key from its type, numbered when taken, and its schema's defaults but never a connection", () => {
    expect(keyFor(TRANSFORM, ["a"])).toBe("transform");
    expect(keyFor(TRANSFORM, ["transform", "transform_2"])).toBe("transform_3");
    expect(defaultConfig(TRANSFORM)).toEqual({ fields: {} });
  });

  it("goes after a port, below its source, and is connected from it", () => {
    const { doc: next, node } = addAfter(doc(), { node: "b", port: "out" }, TRANSFORM, "n1");
    expect(node).toMatchObject({ id: "n1", key: "transform", type: "flow.transform@1", position: { x: 0, y: 280 } });
    expect(next.edges.at(-1)).toEqual({ from: { node: "b", port: "out" }, to: { node: "n1" } });
  });

  it("goes first when added from the start card, beside the other entry steps", () => {
    const { doc: next, node } = addAfter(doc(), null, TRANSFORM, "n1");
    expect(node.position).toEqual({ x: 300, y: 0 });
    expect(entries(next).map((n) => n.id)).toEqual(["a", "n1"]);
  });
});

describe("inserting on an edge", () => {
  it("puts the step between the edge's ends and moves what's below down a row", () => {
    const { doc: next, node } = insertOnEdge(doc(), doc().edges![0]!, TRANSFORM, "n1")!;
    expect(node.position).toEqual({ x: 0, y: ROW });
    expect(next.nodes.find((n) => n.id === "b")!.position).toEqual({ x: 0, y: 2 * ROW });
    expect(next.edges.map(edgeId)).toEqual(["a:out->n1", "n1:out->b"]);
  });

  it("refuses a step that can't continue the flow", () => {
    expect(insertOnEdge(doc(), doc().edges![0]!, IF)).toBeNull();
  });

  it("puts a step before an entry step, which it now leads to", () => {
    const { doc: next } = insertBeforeEntry(doc(), "a", LOOP, "n1")!;
    expect(next.edges.map(edgeId)).toContain("n1:done->a");
    expect(entries(next).map((n) => n.id)).toEqual(["n1"]);
  });
});

describe("deleting", () => {
  it("removes the step, its edges and its declassify entries, and heals a chain through it", () => {
    const chain: GraphDoc = { ...doc(), nodes: [...doc().nodes!, { id: "c", key: "c", type: "flow.transform@1" }],
      edges: [...doc().edges!, { from: { node: "b", port: "out" }, to: { node: "c" } }] };  // prettier-ignore
    const { doc: next, healed } = deleteNode(chain, "b");
    expect(next.nodes!.map((n) => n.id)).toEqual(["a", "c"]);
    expect(next.edges!.map(edgeId)).toEqual(["a:out->c"]);
    expect(healed && edgeId(healed)).toBe("a:out->c");
    expect(next.settings!.declassify).toEqual([]);
  });

  it("heals nothing when the step joins or forks", () => {
    const fork: GraphDoc = { ...doc(), nodes: [...doc().nodes!, { id: "c", key: "c", type: "x@1" }, { id: "d", key: "d", type: "x@1" }],
      edges: [...doc().edges!, { from: { node: "b", port: "out" }, to: { node: "c" } }, { from: { node: "b", port: "out" }, to: { node: "d" } }] };  // prettier-ignore
    expect(deleteNode(fork, "b").healed).toBeNull();
  });

  it("removes one edge", () => {
    expect(deleteEdge(doc(), doc().edges![0]!).edges).toEqual([]);
  });
});

it("draws only edges whose ends exist, each once", () => {
  const edge = (from: string, to: string) => ({ from: { node: from, port: "out" }, to: { node: to } });
  const imported: GraphDoc = { ...doc(), edges: [edge("a", "b"), edge("a", "b"), edge("a", "gone"), edge("gone", "b")] };
  expect(drawableEdges(imported).map(edgeId)).toEqual(["a:out->b"]);
});

describe("connecting", () => {
  it("refuses itself, a duplicate and a cycle", () => {
    const d = doc();
    expect(canConnect(d, { node: "a", port: "out" }, "a")).toBe(false);
    expect(canConnect(d, { node: "a", port: "out" }, "b")).toBe(false);
    expect(canConnect(d, { node: "b", port: "out" }, "a")).toBe(false);
    const both: GraphDoc = { ...d, nodes: [...d.nodes!, { id: "c", key: "c", type: "x@1" }] };
    expect(connect(both, { node: "a", port: "out" }, "c")!.edges!.map(edgeId)).toEqual(["a:out->b", "a:out->c"]);
  });
});

it("keeps what it doesn't touch, byte for byte (4b's Review Focus)", () => {
  const before = doc();
  const { doc: next } = addAfter(before, { node: "b", port: "out" }, TRANSFORM, "n1");
  expect(next.graph_format).toBe(1);
  expect(next.settings).toEqual(before.settings);
  expect(next.nodes.slice(0, 2)).toEqual(before.nodes);
  expect(JSON.stringify(doc())).toBe(JSON.stringify(before)); // the input is never mutated
  const moved = moveNodes(before, new Map([["a", { x: 12.4, y: -3 }]]));
  expect(moved.nodes![0]).toEqual({ ...before.nodes![0], position: { x: 12, y: -3 } });
  expect(moved.nodes![1]).toBe(before.nodes![1]);
});

it("puts the start card a row above the entry steps", () => {
  expect(startPosition(doc())).toEqual({ x: 0, y: -ROW });
  expect(startPosition({ graph_format: 1, nodes: [], edges: [] })).toEqual({ x: 0, y: 0 });
});
