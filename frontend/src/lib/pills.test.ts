// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { formula, literal } from "./config";
import {
  headOf, insertPill, linesOf, parsePath, pillText, removePill, replacePill, sameSegments, segmentsOf, segmentsText, valueOf,
  withDefault, withText, type Segments,
} from "./pills";  // prettier-ignore

const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
const ref = (path: string, extra: object = {}) => ({ $value: { kind: "ref", path, ...extra } });

describe("text and pills", () => {
  it("reads text, a literal's text, a reference and a template as text and pills", () => {
    expect(segmentsOf(undefined)).toEqual({ texts: [""], pills: [] });
    expect(segmentsOf("AP down")).toEqual({ texts: ["AP down"], pills: [] });
    expect(segmentsOf(literal("$value"))).toEqual({ texts: ["$value"], pills: [] });
    expect(segmentsOf(ref("steps.a.output.name"))).toEqual({ texts: ["", ""], pills: [{ ref: "steps.a.output.name" }] });
    const value = template({ text: "AP " }, { ref: "trigger.ap", default: "AP" }, { text: " at " }, { ref: "run.now" });
    expect(segmentsOf(value)).toEqual({
      texts: ["AP ", " at ", ""],
      pills: [{ ref: "trigger.ap", default: "AP" }, { ref: "run.now" }],
    });
  });

  it("joins texts written in several parts, and puts empty text between pills side by side", () => {
    const value = template({ text: "a" }, { text: "b" }, { ref: "run.id" }, { ref: "run.now" });
    expect(segmentsOf(value)).toEqual({ texts: ["ab", "", ""], pills: [{ ref: "run.id" }, { ref: "run.now" }] });
  });

  it("reads nothing it can't write back the same: a formula, a number, an object, a default that isn't text", () => {
    expect(segmentsOf(formula("1 + 1"))).toBeNull();
    expect(segmentsOf(3)).toBeNull();
    expect(segmentsOf({ a: 1 })).toBeNull();
    expect(segmentsOf(literal(3))).toBeNull();
    expect(segmentsOf(template({ ref: "run.id", default: 3 }))).toBeNull();
    expect(segmentsOf(template({ ref: "run.id", text: "x" }))).toBeNull();
    expect(segmentsOf({ $value: { kind: "template", parts: "nope" } })).toBeNull();
  });

  it("writes text as text, a literal's as a literal, and pills as a template without its empty texts", () => {
    expect(valueOf({ texts: [""], pills: [] }, false)).toBeUndefined();
    expect(valueOf({ texts: ["hi"], pills: [] }, false)).toBe("hi");
    expect(valueOf({ texts: ["hi"], pills: [] }, true)).toEqual(literal("hi"));
    expect(valueOf({ texts: ["", ""], pills: [{ ref: "run.now" }] }, false)).toEqual(template({ ref: "run.now" }));
    expect(valueOf({ texts: ["a ", "", " b"], pills: [{ ref: "x.y", default: null }, { ref: "run.id" }] }, false)).toEqual(
      template({ text: "a " }, { ref: "x.y", default: null }, { ref: "run.id" }, { text: " b" }),
    );
  });

  it("writes a long text as parts of the engine's 4,096 characters, counted as Python counts, read back as one", () => {
    const long = "x".repeat(4096) + "𝄞".repeat(5000);
    const s: Segments = { texts: [long, ""], pills: [{ ref: "run.id" }] };
    const written = valueOf(s, false);
    expect(written).toEqual(template({ text: "x".repeat(4096) }, { text: "𝄞".repeat(4096) }, { text: "𝄞".repeat(904) }, { ref: "run.id" }));
    expect(sameSegments(segmentsOf(written)!, s)).toBe(true);
    // Where the engine takes no fixed value, text alone is a template too: split the same way.
    expect(valueOf({ texts: ["y".repeat(5000)], pills: [] }, false, false)).toEqual(template({ text: "y".repeat(4096) }, { text: "y".repeat(904) }));
    // A fixed text isn't a template: the engine takes it whole.
    expect(valueOf({ texts: ["y".repeat(5000)], pills: [] }, false)).toBe("y".repeat(5000));
  });

  it("lays text and pills out as lines: each line's pieces of text, each with the pill after it on that line", () => {
    const s: Segments = { texts: ["Access point ", " stopped.\nLast seen ", ""], pills: [{ ref: "a.name" }, { ref: "run.now" }] };
    expect(linesOf(s)).toEqual([
      [
        { piece: { segment: 0, start: 0, text: "Access point " }, pill: 0 },
        { piece: { segment: 1, start: 0, text: " stopped." }, pill: null },
      ],
      [
        { piece: { segment: 1, start: 10, text: "Last seen " }, pill: 1 },
        { piece: { segment: 2, start: 0, text: "" }, pill: null },
      ],
    ]);
    expect(linesOf({ texts: ["a\n\nb"], pills: [] }).map((line) => line[0]!.piece)).toEqual([
      { segment: 0, start: 0, text: "a" },
      { segment: 0, start: 2, text: "" },
      { segment: 0, start: 3, text: "b" },
    ]);
  });

  it("reads back what it writes", () => {
    const s: Segments = { texts: ["AP ", " at ", ""], pills: [{ ref: "trigger.ap", default: "AP" }, { ref: "run.now" }] };
    expect(sameSegments(segmentsOf(valueOf(s, false))!, s)).toBe(true);
  });

  it("puts a pill at the caret, splitting its text, and takes one away joining the texts either side", () => {
    const s: Segments = { texts: ["AP went offline"], pills: [] };
    const put = insertPill(s, { segment: 0, offset: 3 }, { ref: "trigger.ap" });
    expect(put).toEqual({ texts: ["AP ", "went offline"], pills: [{ ref: "trigger.ap" }] });
    expect(removePill(put, 0)).toEqual({ segments: s, caret: { segment: 0, offset: 3 } });
    expect(insertPill(s, { segment: 0, offset: 99 }, { ref: "run.id" }).texts).toEqual(["AP went offline", ""]);
  });

  it("gives a pill a default, changes it, and takes it away", () => {
    const s: Segments = { texts: ["", ""], pills: [{ ref: "trigger.ap" }] };
    const given = withDefault(s, 0, "AP");
    expect(given.pills[0]).toEqual({ ref: "trigger.ap", default: "AP" });
    expect(withDefault(given, 0, null).pills[0]).toEqual({ ref: "trigger.ap", default: null });
    expect(withDefault(given, 0, undefined).pills[0]).toEqual({ ref: "trigger.ap" });
    expect(replacePill(given, 0, "trigger.site").pills[0]).toEqual({ ref: "trigger.site", default: "AP" });
    expect(withText(given, 1, "!").texts).toEqual(["", "!"]);
  });

  it("says text and pills as braces", () => {
    expect(segmentsText({ texts: ["AP ", " down"], pills: [{ ref: "trigger.ap" }] })).toBe("AP {trigger.ap} down");
  });
});

describe("a reference's path", () => {
  it("parses roots, fields and indexes, and refuses what isn't a path", () => {
    expect(parsePath("steps.list.output.results[0].name")).toEqual([
      { field: "steps" }, { field: "list" }, { field: "output" }, { field: "results" }, { index: 0 }, { field: "name" },
    ]);  // prettier-ignore
    for (const bad of ["", "[0]", "a..b", "a.", "a[01]", "a[-1]", "a.b-c", "a b", "a.[0]"]) expect(parsePath(bad)).toBeNull();
  });

  it("names a pill by its step, a loop or its root, then what it reads", () => {
    expect(pillText("steps.get_site.output.name")).toBe("get_site › name");
    expect(pillText("steps.get_site.output")).toBe("get_site");
    expect(pillText("steps.call.error.message")).toBe("call › error.message");
    expect(pillText("trigger.events[0].ap_name")).toBe("trigger › events[0].ap_name");
    expect(pillText("trigger")).toBe("trigger");
    expect(pillText("run.now")).toBe("run › now");
    expect(pillText("loops.each.item.mac")).toBe("each › item.mac");
    expect(pillText("vars.limit")).toBe("vars › limit");
    expect(pillText("item")).toBe("item");
    expect(headOf("steps.list.output[0].x")).toEqual({ head: "list", rest: "[0].x" });
  });
});
