// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { IF, SWITCH, TRANSFORM } from "../test/nodeTypes";
import { formula, literal, setConfig } from "./config";
import type { Path } from "./schemaForm";
import {
  STALE, applyAll, applyUnapplied, baseOf, isStale, lineageOf, parseNumber, unappliedFile, unappliedId, within,
  type Unapplied, type UnappliedKind,
} from "./unapplied";  // prettier-ignore
import type { GraphDoc, GraphNode, NodeType } from "./workflows";

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const TYPES: Record<string, NodeType> = { "flow.switch@1": SWITCH, "flow.if@1": IF, "flow.transform@1": TRANSFORM };
const typeOf = (n: GraphNode) => TYPES[n.type];

/** An edit held for step A, typed over what `doc` holds there now, as the editor records it. */
function held(doc: GraphDoc, kind: UnappliedKind, pointer: string, path: Path, text: string, more: Partial<Unapplied> = {}): Unapplied {
  const u: Unapplied = {
    id: unappliedId(A, kind, pointer), node: A, kind, pointer, path, label: pointer, text, why: null, base: "", lineage: [], ...more,
  };  // prettier-ignore
  return { ...u, base: baseOf(doc, u), lineage: lineageOf(doc, u) };
}
/** Step A, `fetch`, a transform with this config. */
const fetch = (config: Record<string, unknown>): GraphDoc => ({
  graph_format: 1,
  nodes: [{ id: A, key: "fetch", type: "flow.transform@1", config }],
});

const applied = (result: ReturnType<typeof applyUnapplied>) => {
  if ("problem" in result) throw new Error(result.problem);
  return result;
};

it("keeps a number exactly as typed, or says why not", () => {
  expect(parseNumber("2.", false)).toEqual({ value: 2 });
  expect(parseNumber(" ", false)).toEqual({ value: undefined });
  expect(parseNumber("2.5", true)).toEqual({ problem: "A whole number, like 42." });
  expect(parseNumber("1x", false)).toEqual({ problem: "A number, like 42 or 2.5." });
  expect(parseNumber("1e400", false)).toEqual({ problem: "A number this large can't be kept." });
  // Past 2^53 in any notation, in a whole field or not: Number() rounds it.
  for (const n of ["9007199254740993", "9007199254740993.0", "9007199254740993e0"]) {
    for (const whole of [true, false]) {
      expect(parseNumber(n, whole)).toEqual({ problem: "A whole number this large can't be kept exactly." });
    }
  }
});

it("applies JSON, and keeps a literal envelope a literal", () => {
  const doc = fetch({});
  const text = '{"x": {"$value": {"kind": "ref", "path": "trigger.x"}}}';
  const result = applied(applyUnapplied(doc, held(doc, "json", "/fields", ["fields"], text, { literal: true }), TRANSFORM));
  expect(result.doc.nodes![0]!.config).toEqual({ fields: literal({ x: { $value: { kind: "ref", path: "trigger.x" } } }) });
  expect(result.said).toBeNull(); // a field's own edit is never announced (ruling 8)
});

it("refuses what the graph's format would, with its reason", () => {
  const empty = fetch({});
  expect(applyUnapplied(empty, held(empty, "json", "/fields", ["fields"], '{"n": 1e400}'), TRANSFORM)).toEqual({
    problem: "A number here is too large to keep, so it isn't saved.",
  });
  const crowded = fetch({ fields: Object.fromEntries(Array.from({ length: 2000 }, (_, i) => [`f${i}`, formula("1")])) });
  expect(applyUnapplied(crowded, held(crowded, "formula", "/fields/more", ["fields", "more"], "2"), TRANSFORM)).toEqual({
    problem: "A workflow can hold at most 2,000 references, templates and formulas.",
  });
  expect(applyUnapplied(empty, held(empty, "limit", "/options/max_attempts", ["max_attempts"], "25"), TRANSFORM)).toEqual({
    problem: "A whole number from 1 to 20.",
  });
});

it("renames a key, saying which formulas mention the old one", () => {
  const doc: GraphDoc = {
    graph_format: 1,
    nodes: [
      { id: A, key: "fetch", type: "flow.transform@1" },
      { id: B, key: "use", type: "flow.if@1", config: { condition: formula("steps.fetch.output.n > 1") } },
    ],
  };  // prettier-ignore
  const result = applied(applyUnapplied(doc, held(doc, "key", "", [], "load"), TRANSFORM));
  expect(result.doc.nodes![0]!.key).toBe("load");
  expect(result.note).toBe("1 formula mentions fetch and keeps its text: check it.");
  expect(result.said).toBe("Renamed fetch to load. 1 formula mentions fetch and keeps its text: check it.");
  expect(applyUnapplied(doc, held(doc, "key", "", [], "use"), TRANSFORM)).toEqual({ problem: "Another step is already called use." });
});

it("keeps an edit that takes ports away for its question", () => {
  const doc: GraphDoc = {
    graph_format: 1,
    nodes: [
      { id: A, key: "pick", type: "flow.switch@1", config: { cases: [{ port: "a", when: formula("true") }, { port: "b", when: formula("false") }] } },
      { id: B, key: "right", type: "flow.transform@1" },
    ],
    edges: [{ from: { node: A, port: "b" }, to: { node: B } }],
  };  // prettier-ignore
  const cut = held(doc, "json", "/cases", ["cases"], '[{"port": "a", "when": {"$value": {"kind": "cel", "expr": "true"}}}]');
  const { doc: next, applied: done, left } = applyAll(doc, [cut], typeOf, () => true);
  expect(next).toBe(doc);
  expect(done).toEqual([]);
  expect(left.map((u) => u.why)).toEqual(["Not applied: it removes the port b and its edge to right."]);
});

it("applies each held edit in turn, as one document, the deepest first, and keeps those it can't", () => {
  const doc = fetch({});
  const edits = [
    held(doc, "number", "/n", ["n"], "12", { whole: true }),
    held(doc, "number", "/m", ["m"], "1x"),
    held(doc, "limit", "/options/max_attempts", ["max_attempts"], "5"),
  ];
  const { doc: next, applied: done, left } = applyAll(doc, edits, typeOf, () => true);
  expect(next.nodes![0]).toMatchObject({ config: { n: 12 }, options: { max_attempts: 5 } });
  expect(done.map((u) => u.pointer)).toEqual(["/options/max_attempts", "/n"]); // rank order, not insertion order
  expect(left.map((u) => [u.pointer, u.why])).toEqual([["/m", "A number, like 42 or 2.5."]]);
});

it("applies a value before its entry's rename, whatever the order they were typed in", () => {
  const doc = fetch({ fields: { old: 2 } });
  const rename = held(doc, "name", "/fields/old", ["fields"], "new", { from: "old" });
  const value = held(doc, "number", "/fields/old", ["fields", "old"], "1");
  const { doc: next, left } = applyAll(doc, [rename, value], typeOf, () => true);
  expect(left).toEqual([]);
  expect(next.nodes![0]!.config).toEqual({ fields: { new: 1 } }); // never `{new: 1, old: …}`
});

it("keeps a rename while an edit inside its entry can't be applied", () => {
  const doc = fetch({ fields: { old: 2 } });
  const rename = held(doc, "name", "/fields/old", ["fields"], "new", { from: "old" });
  const value = held(doc, "number", "/fields/old", ["fields", "old"], "1x");
  const { doc: next, left } = applyAll(doc, [rename, value], typeOf, () => true);
  expect(next.nodes![0]!.config).toEqual({ fields: { old: 2 } });
  expect(left.map((u) => [u.kind, u.why])).toEqual([
    ["number", "A number, like 42 or 2.5."],
    ["name", "Not applied: an edit inside it isn't applied yet."],
  ]);
});

it("keeps an edit where what it was typed over has changed, as an undo does", () => {
  const moved = fetch({ sizes: [7, 5] });
  const typed = held(moved, "number", "/sizes/1", ["sizes", 1], "50", { whole: true }); // over the 5
  const undone = fetch({ sizes: [5, 7] }); // the move undone: the second item is the 7 now
  expect(isStale(undone, typed)).toBe(true);
  expect(applyUnapplied(undone, typed, TRANSFORM)).toEqual({ problem: STALE });
  expect(applied(applyUnapplied(moved, typed, TRANSFORM)).doc.nodes![0]!.config).toEqual({ sizes: [7, 50] });
  const data = fetch({ q: literal({ a: 1 }) });
  const json = held(data, "json", "/q", ["q"], '{"a": 2}', { literal: true });
  expect(isStale(fetch({ q: { a: 1 } }), json)).toBe(true); // a literal turned to data under it: asked, never guessed
});

it("tells two items apart when their values match, and an edit beside it never makes it stale", () => {
  const a = { label: "A", amount: 5 };
  const b = { label: "B", amount: 5 };
  const before = fetch({ items: [a, b] });
  const moved = setConfig(before, A, ["items"], [b, a], TRANSFORM).doc; // a move: a new list, the same items
  const typed = held(moved, "number", "/items/1/amount", ["items", 1, "amount"], "50", { whole: true }); // A's amount
  expect(isStale(before, typed)).toBe(true); // the move undone: B's amount, an equal 5, sits there now
  const beside = setConfig(moved, A, ["items", 1, "label"], "A2", TRANSFORM).doc; // A's label edited in place
  expect(isStale(beside, typed)).toBe(false);
  expect(applyUnapplied(before, typed, TRANSFORM)).toEqual({ problem: STALE });
});

it("tells two equal numbers apart after a removal and its undo", () => {
  const before = fetch({ sizes: [5, 5, 7] });
  const removed = setConfig(before, A, ["sizes", 0], undefined, TRANSFORM).doc; // [5, 7]: the second 5 is first now
  const typed = held(removed, "number", "/sizes/0", ["sizes", 0], "50", { whole: true }); // over that second 5
  expect(isStale(before, typed)).toBe(true); // the removal undone: the first 5, an equal value, sits there again
  expect(applyUnapplied(before, typed, TRANSFORM)).toEqual({ problem: STALE });
  const beside = setConfig(removed, A, ["sizes", 1], 8, TRANSFORM).doc; // the 7, edited in place
  expect(isStale(beside, typed)).toBe(false);
});

it("writes edits not applied as a file of their own, never into the graph", () => {
  const doc = fetch({});
  const file = unappliedFile([held(doc, "number", "/n", ["n"], "5x", { label: "Count", why: "A number, like 42 or 2.5." })], () => "fetch");
  expect(file).toEqual({
    format: "dewpoint.unapplied-edits",
    edits: [{ step: "fetch", field: "Count", at: "/n", text: "5x", why: "A number, like 42 or 2.5." }],
  });
});

describe("which edits a change covers", () => {
  it("covers a part and what's below it, never a sibling that shares its prefix", () => {
    const doc = fetch({});
    const at = (pointer: string) => held(doc, "json", pointer, [], "");
    expect([at("/fields"), at("/fields/x"), at("/fieldsx")].map(within(A, "/fields"))).toEqual([true, true, false]);
    expect(within(B, "/fields")(at("/fields"))).toBe(false);
    expect(within(A, "")(held(doc, "key", "", [], "load"))).toBe(true); // the whole step: a deletion's
  });

  it("says when an edit's step is gone", () => {
    const doc = fetch({});
    expect(applyUnapplied(doc, { ...held(doc, "json", "/x", ["x"], "1"), node: B }, TRANSFORM)).toEqual({
      problem: "Its step is no longer in the draft.",
    });
  });
});

it("never applies a formula past the engine's limit, and says why (the review of 97235e3)", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [{ id: A, key: "check", type: "flow.if@1", config: { condition: formula("true") } }] };
  const long = `true${" ".repeat(16_380)}&& false`; // 16,392 characters: cut at 16,384 it would read `true`
  const result = applyUnapplied(doc, held(doc, "formula", "/condition", ["condition"], long), IF);
  expect(result).toEqual({ problem: "A formula can be at most 16,384 characters: this one has 16,392, so it isn't saved." });
});
