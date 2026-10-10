// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { NO_VALUE, OP_WORDS, opsFor, read, rowCel, valueProblem, write, type Condition, type Op, type Row } from "./builder";
import type { Guard } from "./data";

const g = (kind: Guard["kind"], path: string, size: number | null = null): Guard => ({ kind, path, size });
const EV = "trigger.events[0].ev_type";
const EVENT_GUARDS = [
  g("present", "trigger.events"), g("is_list", "trigger.events"), g("min_size", "trigger.events", 0),
  g("is_map", "trigger.events[0]"), g("present", EV),
];  // prettier-ignore
const row = (over: Partial<Row>): Row => ({ path: "steps.s.output.name", op: "is", value: { kind: "text", text: "x" }, guards: [], nullTest: false, ...over });

describe("the condition builder's formulas", () => {
  it("writes each comparison as its guards, its null test, a type test where the operator needs one, and the test", () => {
    expect(rowCel(row({ path: EV, guards: EVENT_GUARDS, nullTest: true, value: { kind: "text", text: "AP_DISCONNECTED" } }))).toBe(
      '(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type == "AP_DISCONNECTED")',
    );
    expect(rowCel(row({ path: "steps.l.output.total", op: "more", value: { kind: "number", text: "0" }, nullTest: true }))).toBe(
      "(steps.l.output.total != null && (type(steps.l.output.total) == type(0) || type(steps.l.output.total) == type(0.0)) && steps.l.output.total > 0)",
    );
    expect(rowCel(row({ op: "starts_with", value: { kind: "text", text: "HQ-" } }))).toBe(
      '(type(steps.s.output.name) == type("") && steps.s.output.name.startsWith("HQ-"))',
    );
    expect(rowCel(row({ op: "is_missing", guards: [g("present", "steps.s.output.tz")], path: "steps.s.output.tz", value: null }))).toBe(
      "!(has(steps.s.output.tz))",
    );
  });

  it("names no type: every type test compares with a value's type", () => {
    const all = rowCel(row({ path: EV, guards: EVENT_GUARDS, op: "contains" }));
    expect(all).not.toMatch(/==\s*(map|list|string|int|double|bool)\b/);
  });

  it("joins comparisons by all or any, a group in parentheses, each item on its line", () => {
    const c: Condition = {
      match: "all",
      items: [
        row({ path: "steps.a.output.n", op: "is", value: { kind: "number", text: "5" } }),
        { match: "any", rows: [row({ op: "starts_with", value: { kind: "text", text: "HQ-" } }), row({ op: "is_true", value: null, path: "steps.a.output.up" })] },
      ],
    };
    expect(write(c)).toBe(
      '(steps.a.output.n == 5)\n&& ((type(steps.s.output.name) == type("") && steps.s.output.name.startsWith("HQ-")) || (steps.a.output.up == true))',
    );
    expect(write({ match: "any", items: [] })).toBeUndefined();
  });

  it("reads back what it wrote, and only that", () => {
    const c: Condition = {
      match: "any",
      items: [
        row({ path: EV, guards: EVENT_GUARDS, nullTest: true, value: { kind: "text", text: 'a "quoted" \\ value\n' } }),
        row({ path: "steps.l.output.total", op: "at_most", value: { kind: "number", text: "-2.5e3" }, nullTest: true }),
        { match: "all", rows: [row({ op: "is_not" }), row({ op: "is_missing", value: null, path: "steps.s.output.tz", guards: [g("present", "steps.s.output.tz")] })] },
        row({ path: "steps.l.output.results", op: "is_empty", value: null }),
        row({ path: "steps.s.output.tz", op: "is_there", value: null, guards: [g("present", "steps.s.output.tz")], nullTest: true }),
      ],
    };
    const text = write(c)!;
    expect(read(text)).toEqual(c);
    for (const foreign of [
      'size(steps.list_devices.output.results.filter(d, d.status == "disconnected")) > 2',
      "steps.s.output.name == \"x\"", // no parentheses: not the builder's
      "(type(steps.s.output.name) == string && steps.s.output.name.contains(\"x\"))", // a type's name
      `${text} `,
      "(steps.a.output.n == 5) && (steps.a.output.m == 6)", // joined on one line
    ]) {
      expect(read(foreign)).toBeNull();
    }
  });

  it("keeps a formula with text JSON doesn't read a formula, and never fails on it (the review of revision 1)", () => {
    for (const foreign of [
      '(trigger.name == "\\x41")', // CEL's hexadecimal escape: a formula that runs, but not text the builder writes
      '(trigger.name == "\\101")',
      '(type(trigger.name) == type("") && trigger.name.startsWith("\\x41"))',
    ]) {
      expect(() => read(foreign)).not.toThrow();
      expect(read(foreign)).toBeNull();
    }
  });

  it("names the value it tests in \"is there\" and \"is missing\", and reads that value back (the review of revision 1)", () => {
    const events = [g("present", "trigger.events"), g("is_list", "trigger.events"), g("min_size", "trigger.events", 0)];
    const cases: [Row, string][] = [
      // A field always there in each item: the list's guards say only that an item is there, so the field is named.
      [
        row({ path: "trigger.events[0].name", op: "is_there", value: null, guards: [...events, g("is_map", "trigger.events[0]")] }),
        "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].name))",
      ],
      // The same, with the guards the scope gives a declared list's item's required field (Task 1 runs this formula).
      [
        row({ path: "trigger.olist[0].name", op: "is_there", value: null, guards: [g("present", "trigger.olist"), g("min_size", "trigger.olist", 0)] }),
        "(has(trigger.olist) && size(trigger.olist) > 0 && has(trigger.olist[0].name))",
      ],
      // An item: the size its guards test names it.
      [
        row({ path: "trigger.events[0]", op: "is_missing", value: null, guards: events }),
        "!(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0)",
      ],
      // A value its own guard names already.
      [row({ path: "trigger.events", op: "is_there", value: null, guards: [g("present", "trigger.events")] }), "(has(trigger.events))"],
      // A value that may be null, and is always there otherwise: its null test names it.
      [row({ path: "steps.l.output.total", op: "is_there", value: null, nullTest: true }), "(steps.l.output.total != null)"],
    ];
    for (const [r, cel] of cases) {
      expect(rowCel(r)).toBe(cel);
      const back = read(cel);
      expect(back?.items[0]).toMatchObject({ path: r.path, op: r.op });
      expect(write(back!)).toBe(cel);
    }
  });

  it("tells a list's first item being there from the list not being empty, each read back as itself (the review of revision 2)", () => {
    const item = row({ path: "trigger.labels[0]", op: "is_there", value: null, guards: [g("is_list", "trigger.labels"), g("min_size", "trigger.labels", 0)] });
    const list = row({ path: "trigger.labels", op: "is_not_empty", value: null });
    expect(rowCel(list)).toBe("(type(trigger.labels) == type([]) && size(trigger.labels) != 0)");
    expect(rowCel(item)).toBe("(type(trigger.labels) == type([]) && size(trigger.labels) > 0)");
    expect(read(rowCel(item))?.items[0]).toMatchObject({ path: "trigger.labels[0]", op: "is_there" });
    expect(read(rowCel(list))?.items[0]).toMatchObject({ path: "trigger.labels", op: "is_not_empty" });
  });

  it("reads every comparison back as the value, operator and literal it was written for (the review of revision 2)", () => {
    // The shapes of guards the scope gives: none, a field's own, a list's and its item's, an item's field below them.
    const X = "trigger.xs";
    const shapes: [string, Guard[]][] = [
      ["trigger.a", []],
      ["trigger.a", [g("present", "trigger.a")]],
      [X, []],
      [X, [g("present", X)]],
      [`${X}[0]`, [g("min_size", X, 0)]],
      [`${X}[0]`, [g("is_list", X), g("min_size", X, 0)]],
      [`${X}[2]`, [g("present", X), g("is_list", X), g("min_size", X, 2)]],
      [`${X}[0].f`, [g("is_list", X), g("min_size", X, 0)]],
      [`${X}[0].f`, [g("present", X), g("min_size", X, 0), g("is_map", `${X}[0]`)]],
      [`${X}[0].f`, [g("is_list", X), g("min_size", X, 0), g("is_map", `${X}[0]`), g("present", `${X}[0].f`)]],
    ];
    const ops = Object.keys(OP_WORDS) as Op[];
    const seen = new Map<string, string>();
    for (const [path, guards] of shapes) {
      for (const nullTest of [false, true]) {
        for (const op of ops) {
          for (const value of NO_VALUE.has(op) ? [null] : [{ kind: "text", text: "a" } as const, { kind: "number", text: "3" } as const]) {
            const cel = rowCel({ path, op, value, guards, nullTest });
            const said = `${path} ${op} ${JSON.stringify(value)}`;
            expect(read(cel)?.items[0], `${said} wrote ${cel}`).toMatchObject({ path, op, value });
            if (seen.has(cel) && seen.get(cel)!.split(" ").slice(0, 2).join(" ") !== `${path} ${op}`) throw new Error(`${said} and ${seen.get(cel)} both write ${cel}`);
            seen.set(cel, said);
          }
        }
      }
    }
  });

  it("offers \"is there\" and \"is missing\" only for a value that may be missing (the review of revision 1)", () => {
    expect(opsFor(["object"], null, false)).toEqual([]);
    expect(opsFor([], null, false)).not.toContain("is_there");
    expect(opsFor(["string", "integer"], null, false)).not.toContain("is_missing");
    expect(opsFor(["string", "integer"], null, true)).toContain("is_there");
  });

  it("offers the operators a value's type takes, never ordering a date and time", () => {
    expect(opsFor(["string"], null, false)).toEqual(["is", "is_not", "contains", "starts_with", "ends_with"]);
    expect(opsFor(["string"], "date-time", true)).toEqual(["is", "is_not", "is_there", "is_missing"]);
    expect(opsFor(["integer", "null"], null, true)).toEqual(["is", "is_not", "more", "less", "at_least", "at_most", "is_there", "is_missing"]);
    expect(opsFor(["boolean"], null, false)).toEqual(["is_true", "is_false"]);
    expect(opsFor(["array"], null, false)).toEqual(["is_empty", "is_not_empty"]);
    expect(opsFor(["object"], null, true)).toEqual(["is_there", "is_missing"]);
    expect(opsFor([], null, true)).toContain("more");
  });

  it("takes a number only as JSON writes one, finite, and whole within CEL's int; the loop's position whole", () => {
    expect(valueProblem({ kind: "number", text: "3" }, "steps.a.output.n")).toBeNull();
    expect(valueProblem({ kind: "number", text: "-0.5e3" }, "steps.a.output.n")).toBeNull();
    for (const bad of ["05", "5.", ".5", "1_000", "0x10", "abc", ""]) expect(valueProblem({ kind: "number", text: bad }, "x")).not.toBeNull();
    expect(valueProblem({ kind: "number", text: "1e400" }, "x")).toBe("This number is too large.");
    expect(valueProblem({ kind: "number", text: "9223372036854775808" }, "x")).toBe("This whole number is too large.");
    expect(valueProblem({ kind: "number", text: "1.5" }, "index")).toBe("The loop's position is a whole number.");
    expect(valueProblem({ kind: "text", text: "a\ud800b" }, "x")).not.toBeNull();
    expect(valueProblem({ kind: "text", text: "emoji 😀" }, "x")).toBeNull();
  });
});
