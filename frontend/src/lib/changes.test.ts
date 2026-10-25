// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { DEVICE_UPDATE, UPDATE } from "../test/nodeTypes";
import {
  NO_MEMORY, WORDS, bodyObject, brief, changedCount, clearIn, clearNames, keepIn, kindIn, kindIndex, reindexed, rowsOf, setIn, summaryOf,
} from "./changes";  // prettier-ignore
import { formula } from "./config";
import { branchesOf, fieldsOf, kindOf, offeredOf, propertiesOf } from "./schemaForm";

const body = fieldsOf(UPDATE).find((f) => f.name === "body")!;
const offered = offeredOf(body);

describe("rows", () => {
  it("lists each setting set, cleared or added, by title, with what it does", () => {
    const rows = rowsOf(offered, { rogue: { enabled: true }, name: "hq" }, ["tags"], ["vlan_id"]);
    expect(rows.map((r) => [r.spec.label, r.state])).toEqual([["Name", "set"], ["Rogue", "set"], ["Tags", "clear"], ["VLAN ID", "pending"]]);
    expect(changedCount(rows)).toBe(3);
  });
  it("puts a create's required settings first, given or not, in their order", () => {
    const rows = rowsOf(offered, { enabled: true, tags: [] }, [], [], ["vlan_id", "name"]);
    expect(rows.map((r) => [r.name, r.state])).toEqual([["vlan_id", "pending"], ["name", "pending"], ["enabled", "set"], ["tags", "set"]]);
  });
  it("says a setting both set and cleared, and leaves out what the schema doesn't describe or Mist sets", () => {
    const rows = rowsOf(offered, { name: "hq", id: "x", nope: 1 }, ["name"], []);
    expect(rows.map((r) => [r.name, r.state])).toEqual([["name", "both"]]);
  });
  it("reads only a plain body and a plain list of names", () => {
    expect(bodyObject({})).toEqual({});
    expect(bodyObject({ body: formula("steps.x.output") })).toBeNull();
    expect(clearNames({ clear: ["a"] })).toEqual(["a"]);
    expect(clearNames({ clear: formula("[]") })).toBeNull();
  });
});

describe("one write each", () => {
  it("sets, clears and keeps a setting in the body and `clear` together", () => {
    const start = { mode: "merge", body: { name: "hq", rogue: { enabled: true } } };
    const cleared = clearIn(start, "rogue");
    expect(cleared).toEqual({ mode: "merge", body: { name: "hq" }, clear: ["rogue"] });
    expect(setIn(cleared, "rogue", { enabled: true })).toEqual(start);
    expect(setIn(cleared, "rogue", undefined)).toEqual({ mode: "merge", body: { name: "hq" } }); // Set, nothing given yet
    expect(keepIn(cleared, "rogue")).toEqual({ mode: "merge", body: { name: "hq" } });
    expect(keepIn(start, "name")).toEqual({ mode: "merge", body: { rogue: { enabled: true } } });
  });
  it("never writes into a body a formula gives", () => {
    const start = { body: formula("steps.x.output"), clear: ["tags"] };
    expect(clearIn(start, "name")).toEqual({ body: formula("steps.x.output"), clear: ["tags", "name"] });
    expect(keepIn(start, "tags")).toEqual({ body: formula("steps.x.output") });
  });
});

describe("a device's kind", () => {
  const device = fieldsOf(DEVICE_UPDATE).find((f) => f.name === "body")!;
  const branches = branchesOf(device);
  const kind = kindOf(branches)!;
  const names = branches.map((b) => offeredOf(b, kind.name).map((p) => p.name));

  it("reads an update's kind from its value, the one chosen, the settings listed, else the first", () => {
    expect(kindIndex("update", { type: "sensor" }, [], kind, names, "camera")).toBe(1);
    expect(kindIndex("update", {}, ["name"], kind, names, "sensor")).toBe(1);
    expect(kindIndex("update", { range: 3 }, ["range"], kind, names, null)).toBe(1);
    expect(kindIndex("update", { name: "a" }, ["name"], kind, names, null)).toBe(0);
    expect(kindIndex("create", { name: "a" }, ["name"], kind, names, "sensor")).toBeNull();
  });
  it("keeps the changes the new kind has, drops the others, and writes its value where it's held", () => {
    const start = { body: { name: "a", zoom: 2 }, clear: ["notes"] };
    expect(kindIn(start, kind, 1, names[1]!, false)).toEqual({ config: { body: { name: "a" }, clear: ["notes"] }, kept: ["name", "notes"], dropped: ["zoom"] });
    expect(kindIn({ body: { type: "camera", zoom: 2 } }, kind, 1, names[1]!, true).config).toEqual({ body: { type: "sensor" } });
  });
  it("says what a change of kind kept and dropped", () => {
    expect(WORDS.kindChanged("Sensor", ["Name", "Notes"], ["Zoom"])).toBe("Kind changed to Sensor: Name and Notes are kept; Zoom is dropped, as a Sensor doesn't have it.");
    expect(WORDS.kindChanged("Sensor", [], ["Zoom", "Mode"])).toBe("Kind changed to Sensor: Zoom and Mode are dropped, as a Sensor doesn't have them.");
    expect(WORDS.kindChanged("Sensor", ["Name"], [])).toBe("Kind changed to Sensor: every change is kept.");
  });
});

describe("words", () => {
  it("counts an update's changes and a create's settings", () => {
    expect(WORDS.count("update", 3, 93)).toBe("3 of 93 settings change; the others stay as they are.");
    expect(WORDS.count("create", 3, 95)).toBe("3 of 95 settings given; Mist uses its defaults for the others.");
  });
  it("sums up the changes for a read-only view", () => {
    const config = { body: { name: "hq", auto_upgrade: { enabled: true, version: "stable", custom: { ap41: "1.2" } }, api_secret: "x" }, clear: ["tags"] };
    const rows = rowsOf(offered, config.body, config.clear, []);
    expect(summaryOf("update", rows, config.body, "replace", propertiesOf)).toEqual({
      head: "Replace them · 4 changes",
      lines: [
        { name: "api_secret", label: "API secret", text: "set: a sensitive value" },
        { name: "auto_upgrade", label: "Auto upgrade", text: "set: Enabled yes, Version stable, Custom versions 1 setting" },
        { name: "name", label: "Name", text: "set: hq" },
        { name: "tags", label: "Tags", text: "cleared" },
      ],
    });
    expect(summaryOf("create", rows.slice(2, 3), config.body, undefined, propertiesOf).head).toBe("1 setting given");
  });
  it("says a value in a few words", () => {
    expect(brief(undefined, { $value: { kind: "ref", path: "steps.get_site.output.id" } })).toBe("steps.get_site.output.id");
    expect([brief(undefined, false), brief(undefined, [1, 2]), brief(undefined, formula("1"))]).toEqual(["no", "2 items", "computed when the step runs"]);
  });
});

describe("what the list can't read stays as it is (the final review)", () => {
  const device = fieldsOf(DEVICE_UPDATE).find((f) => f.name === "body")!;
  const branches = branchesOf(device);
  const kind = kindOf(branches)!;
  const names = branches.map((b) => offeredOf(b, kind.name).map((p) => p.name));

  it("never writes into a body a formula gives", () => {
    const start = { body: formula("steps.x.output"), clear: ["tags"] };
    expect(setIn(start, "tags", undefined)).toEqual(start);
    expect(setIn(start, "tags", ["a"])).toEqual(start);
  });
  it("leaves a `clear` it can't read as it is, whatever the action", () => {
    const clear = formula("[]");
    expect(setIn({ body: { name: "hq" }, clear }, "enabled", true)).toEqual({ body: { name: "hq", enabled: true }, clear });
    expect(keepIn({ body: { name: "hq" }, clear }, "name")).toEqual({ body: {}, clear });
    expect(clearIn({ body: { name: "hq" }, clear }, "name")).toEqual({ body: { name: "hq" }, clear });
    expect(kindIn({ body: { name: "a" }, clear }, kind, 1, names[1]!, false).config).toEqual({ body: { name: "a" }, clear });
  });
  it("keeps, on a change of kind, the names no kind offers", () => {
    expect(kindIn({ body: { name: "a" }, clear: ["type", "zoom"] }, kind, 1, names[1]!, false, names.flat()).config).toEqual({ body: { name: "a" }, clear: ["type"] });
  });
  it("reads an update's kind from its settings when the one chosen here no longer fits them (an Undo)", () => {
    expect(kindIndex("update", { name: "a", zoom: 2 }, ["name", "zoom"], kind, names, "sensor")).toBe(0);
  });
});

describe("what's remembered under a list's items (F5)", () => {
  it("follows each item to its new place, nested pointers too; a removed item's is forgotten, a sibling's untouched", () => {
    const memory = {
      ...NO_MEMORY,
      shown: { "/body/networks/0": ["subnet"], "/body/networks/2/vlans": ["id"], "/body/networks2/1": ["name"] },
      entries: { "/body/networks/1/labels": ["a"] },
      open: "/body/networks/2",
      adding: { pointer: "/body/networks/1/labels", parts: ["name"] },
    };
    // [c, b]: the third item first, the second after it, the first removed.
    expect(reindexed(memory, "/body/networks", [2, 1])).toEqual({
      shown: { "/body/networks/0/vlans": ["id"], "/body/networks2/1": ["name"] },
      entries: { "/body/networks/1/labels": ["a"] },
      open: "/body/networks/0",
      adding: { pointer: "/body/networks/1/labels", parts: ["name"] },
    });
    expect(reindexed(memory, "/body/networks", [0])).toMatchObject({ open: null, adding: null, entries: {} });
    expect(reindexed({ ...memory, open: "/body/networks" }, "/body/networks", [1, 0])).toMatchObject({ open: "/body/networks" });
  });
});
