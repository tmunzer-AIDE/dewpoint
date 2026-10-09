// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { IF, SWITCH } from "../test/nodeTypes";
import {
  CEL_WORDS, admission, fixedOf, formula, formulaOf, freePort, isPlainRef, keyProblem, kindOf, parseJson, referenceText,
  renameEntry, renameKey, renamePort, rootOf, setAt, setConfig, setOptions, valueAt,
} from "./config";  // prettier-ignore
import type { GraphDoc } from "./workflows";

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const C = "00000000-0000-4000-8000-00000000000c";

/** A switch `pick` whose cases a and b lead to `left` and `right`, and whose default port leads to `right` too. */
const switchDoc = (): GraphDoc => ({
  graph_format: 1,
  nodes: [
    { id: A, key: "pick", type: "flow.switch@1", config: { cases: [{ port: "a", when: formula("true") }, { port: "b", when: formula("false") }] } },
    { id: B, key: "left", type: "flow.transform@1", config: { fields: { x: { $value: { kind: "ref", path: "steps.pick.output.n" } } } } },
    { id: C, key: "right", type: "flow.transform@1", config: {} },
  ],
  edges: [
    { from: { node: A, port: "a" }, to: { node: B } },
    { from: { node: A, port: "b" }, to: { node: C } },
    { from: { node: A, port: "default" }, to: { node: C } },
  ],
});  // prettier-ignore

describe("values", () => {
  it("tells a fixed value from a computed one", () => {
    expect(kindOf("text")).toBeNull();
    expect(kindOf({ $value: { kind: "cel", expr: "1" } })).toBe("cel");
    expect(kindOf({ $value: { kind: "nope" } })).toBe("unknown");
    expect(fixedOf({ $value: { kind: "literal", value: { $value: 1 } } })).toEqual({ $value: 1 });
    expect(formulaOf(formula("a + 1"))).toBe("a + 1");
  });

  it("reads a reference or a template as text", () => {
    expect(referenceText({ $value: { kind: "ref", path: "steps.a.output" } })).toBe("steps.a.output");
    expect(referenceText({ $value: { kind: "template", parts: [{ text: "Hi " }, { ref: "trigger.name" }] } })).toBe("Hi {trigger.name}");
    expect(isPlainRef({ $value: { kind: "ref", path: "steps.a.output" } })).toBe(true);
    expect(isPlainRef({ $value: { kind: "ref", path: "steps.a.output", default: 0 } })).toBe(false);
  });
});

describe("JSON text", () => {
  it("refuses a number JSON.parse would change", () => {
    expect(parseJson('{"n": 1e400}')).toEqual({ problem: "A number here is too large to keep, so it isn't saved." });
    // Past 2^53, whatever its notation: plain, decimal or with an exponent, JSON.parse rounds it.
    for (const n of ["9007199254740993", "9007199254740993.0", "9007199254740993e0", "-9.007199254740993e15"]) {
      expect(parseJson(`[${n}]`)).toEqual({ problem: "A whole number here is too large to keep exactly, so it isn't saved." });
    }
    // A string's digits, the largest safe whole number and an exponent within it are kept as they are.
    expect(parseJson('{"id": "9007199254740993", "n": 9007199254740991, "x": 1.5e3, "y": 0.1}')).toEqual({
      value: { id: "9007199254740993", n: 9007199254740991, x: 1500, y: 0.1 },
    });
    expect(parseJson("{")).toEqual({ problem: "This isn't valid JSON, so it isn't saved." });
    expect(parseJson("  ")).toEqual({ value: undefined });
  });

  it("finds what the graph's format refuses", () => { // nesting past 64 levels, more than 2,000 computed values
    const nested = (n: number): unknown => (n === 0 ? 1 : [nested(n - 1)]);
    const holding = (value: unknown): GraphDoc => ({
      graph_format: 1,
      nodes: [{ id: A, key: "a", type: "flow.transform@1", config: { fields: { x: value } } }],
    });
    // The graph is level 1, its nodes 2, a node 3, its config 4, `fields` 5: `x`'s arrays start at 6.
    expect(admission(holding(nested(59)))).toBeNull();
    expect(admission(holding(nested(60)))).toBe("Values can be nested at most 64 levels deep.");
    const many = Object.fromEntries(Array.from({ length: 2001 }, (_, i) => [`f${i}`, formula("1")]));
    expect(admission(holding(many))).toBe("A workflow can hold at most 2,000 references, templates and formulas.");
    expect(admission(holding(Number.POSITIVE_INFINITY))).toBe("A number in the draft isn't finite, so it couldn't be saved.");
  });
});

describe("paths", () => {
  it("copies only along the path, and keeps what it doesn't touch", () => {
    const config = { a: { b: 1 }, keep: { deep: [1, 2] } };
    const next = setAt(config, ["a", "b"], 2) as typeof config;
    expect(next).toEqual({ a: { b: 2 }, keep: { deep: [1, 2] } });
    expect(next.keep).toBe(config.keep);
    expect(config.a.b).toBe(1);
  });

  it("keeps a list's and an item's lineage through edits in place, never through a move or a removal", () => {
    const item = { a: 1 };
    const list = [item, { a: 2 }];
    const edited = setAt({ l: list }, ["l", 0, "a"], 5) as { l: { a: number }[] };
    expect(rootOf(edited.l)).toBe(rootOf(list)); // the same list, edited in place
    expect(rootOf(edited.l[0]!)).toBe(rootOf(item)); // the same item
    expect(rootOf([...list].reverse())).not.toBe(rootOf(list)); // a move makes a new list
    const removed = setAt({ l: list }, ["l", 0], undefined) as { l: unknown[] };
    expect(rootOf(removed.l)).not.toBe(rootOf(list)); // so does a removal: the items after it have moved
    const appended = setAt({ l: list }, ["l", 2], { a: 3 }) as { l: unknown[] };
    expect(rootOf(appended.l)).toBe(rootOf(list)); // an item written at the end moves none
  });

  it("removes a property, and splices a list's item, for undefined", () => {
    expect(setAt({ a: 1, b: 2 }, ["a"], undefined)).toEqual({ b: 2 });
    expect(setAt({ l: [1, 2, 3] }, ["l", 1], undefined)).toEqual({ l: [1, 3] });
    expect(valueAt({ l: [{ x: 5 }] }, ["l", 0, "x"])).toBe(5);
    expect(valueAt({ l: 1 }, ["l", "x"])).toBeUndefined();
  });
});

describe("setConfig", () => {
  it("drops only the lost ports' edges", () => {
    const doc = switchDoc();
    const { doc: next, dropped } = setConfig(doc, A, ["cases", 1], undefined, SWITCH);
    expect(dropped).toEqual([doc.edges![1]]);
    expect(next.edges).toEqual([doc.edges![0], doc.edges![2]]);
  });

  it("keeps every edge when a change takes no port away", () => {
    const doc = switchDoc();
    const { doc: next, dropped } = setConfig(doc, A, ["cases", 0, "when"], formula("1 > 0"), SWITCH);
    expect(dropped).toEqual([]);
    expect(next.edges).toBe(doc.edges);
  });

  it("keeps what it doesn't touch", () => {
    const doc = switchDoc();
    const { doc: next } = setConfig(doc, A, ["cases", 0, "when"], formula("1 > 0"), SWITCH);
    expect(next.nodes![1]).toBe(doc.nodes![1]);
    expect((next.nodes![0]!.config!.cases as unknown[])[1]).toBe((doc.nodes![0]!.config!.cases as unknown[])[1]);
  });
});

describe("ports", () => {
  it("keeps a renamed case's edges", () => {
    const result = renamePort(switchDoc(), A, 0, "big", SWITCH);
    if ("problem" in result) throw new Error(result.problem);
    expect(result.doc.edges![0]!.from).toEqual({ node: A, port: "big" });
    expect((result.doc.nodes![0]!.config!.cases as { port: string }[])[0]!.port).toBe("big");
  });

  it("refuses a name the graph's format refuses, or one another port has", () => {
    expect(renamePort(switchDoc(), A, 0, "Big", SWITCH)).toEqual({
      problem: "A port's name starts with a lowercase letter, then lowercase letters, digits or _, up to 31 characters.",
    });
    expect(renamePort(switchDoc(), A, 0, "default", SWITCH)).toEqual({ problem: "Another port of this step is already called default." });
  });

  it("renames a map's entry in place, never to $value, an empty name or a taken one", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [{ id: A, key: "t", type: "flow.transform@1", config: { fields: { x: 1, y: 2 } } }],
    };
    const renamed = renameEntry(doc, A, ["fields"], "x", "constructor"); // a name, not Object's own
    if ("problem" in renamed) throw new Error(renamed.problem);
    expect(Object.entries(renamed.doc.nodes![0]!.config!.fields as object)).toEqual([["constructor", 1], ["y", 2]]);
    expect(renameEntry(doc, A, ["fields"], "x", "$value")).toEqual({
      problem: "A name can't be $value: the engine would read the whole value as computed.",
    });
    expect(renameEntry(doc, A, ["fields"], "x", "")).toEqual({ problem: "A name can't be empty." });
    expect(renameEntry(doc, A, ["fields"], "x", "y")).toEqual({ problem: "There's already one called y." });
  });

  it("names a new case's port after the first free case_N", () => {
    expect(freePort(switchDoc().nodes![0]!, SWITCH)).toBe("case_1");
  });

  it("drops the error port's edges when errors no longer go there", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [{ id: A, key: "check", type: "flow.if@1", options: { on_error: "port" } }, { id: B, key: "alarm", type: "flow.transform@1" }],
      edges: [{ from: { node: A, port: "error" }, to: { node: B } }],
    };  // prettier-ignore
    const { doc: next, dropped } = setOptions(doc, A, { on_error: "fail" }, IF);
    expect(dropped).toHaveLength(1);
    expect(next.nodes![0]).not.toHaveProperty("options");
    expect(next.edges).toEqual([]);
  });

  it("writes only the options the step sets, and never the default failure", () => {
    const { doc: next } = setOptions(switchDoc(), A, { on_error: "continue", max_attempts: 5, timeout_s: null }, SWITCH);
    expect(next.nodes![0]!.options).toEqual({ on_error: "continue", max_attempts: 5 });
  });
});

describe("keys", () => {
  it("says what's wrong with a key, or nothing", () => {
    const doc = switchDoc();
    expect(keyProblem(doc, A, "pick_2")).toBeNull();
    expect(keyProblem(doc, A, "pick")).toBeNull(); // its own
    expect(keyProblem(doc, A, "Left")).toBe("A key starts with a lowercase letter, then lowercase letters, digits or _, up to 63 characters.");
    expect(keyProblem(doc, A, "left")).toBe("Another step is already called left.");
    for (const word of CEL_WORDS) expect(keyProblem(doc, A, word)).toBe(`${word} can't be a key: formulas couldn't name the step.`);
  });

  it("renames every structured reference", () => {
    const doc: GraphDoc = {
      ...switchDoc(),
      settings: { outputs: { n: { $value: { kind: "template", parts: [{ text: "n=" }, { ref: "steps.pick.output.n" }] } } } },
    };
    const { doc: next } = renameKey(doc, A, "route");
    expect(next.nodes![0]!.key).toBe("route");
    expect(next.nodes![1]!.config).toEqual({ fields: { x: { $value: { kind: "ref", path: "steps.route.output.n" } } } });
    expect(next.settings!.outputs).toEqual({ n: { $value: { kind: "template", parts: [{ text: "n=" }, { ref: "steps.route.output.n" }] } } });
    expect(next.nodes![2]).toBe(doc.nodes![2]);
  });

  it("leaves a reference to a longer key alone, and a fixed value's data", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [
        { id: A, key: "pick", type: "flow.if@1" },
        {
          id: B, key: "x", type: "flow.transform@1",
          config: { fields: {
            a: { $value: { kind: "ref", path: "steps.picker.output" } },
            b: { $value: { kind: "literal", value: { $value: { kind: "ref", path: "steps.pick.output" } } } },
          } },
        },
      ],
    };  // prettier-ignore
    expect(renameKey(doc, A, "route").doc.nodes![1]).toBe(doc.nodes![1]);
  });

  it("counts the formulas that mention it", () => {
    // A mention, not a reference: CEL isn't parsed here, so `steps["pick"]` and the text "pick" count, `picker` doesn't.
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [
        { id: A, key: "pick", type: "flow.if@1" },
        { id: B, key: "x", type: "flow.if@1", config: { condition: formula("steps.pick.output.n > 1 && loops.pick.index == 0") } },
        { id: C, key: "y", type: "flow.if@1", config: { condition: formula('steps["pick"].output == "pick"') } },
        { id: "00000000-0000-4000-8000-00000000000d", key: "z", type: "flow.if@1", config: { condition: formula("steps.picker.output") } },
      ],
    };  // prettier-ignore
    expect(renameKey(doc, A, "route").mentions).toBe(2);
  });
});
