// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { DEVICE_EVENTS, MIST } from "../test/triggers";
import {
  addField, fieldOrder, inputFieldOf, inputOf, inputRows, nameProblem, removeField, renameField, sameSchema, setField, setSettings, shapeRows,
  topicShaped,
} from "./input";  // prettier-ignore
import type { GraphDoc } from "./workflows";

const SCHEMA = {
  type: "object",
  properties: {
    site: { type: "string", title: "Site" },
    token: { type: "string", title: "API token", description: "The ticketing system's token for this site.", "x-sensitive": true },
    floor: { type: "integer", default: 0 },
    band: { type: "string", enum: ["2.4 GHz", "5 GHz"], default: "5 GHz" },
    at: { type: "string", format: "date-time" },
    tags: { type: "array", items: { type: "string" } },
    code: { type: "string", minLength: 3 },
  },
  required: ["site", "token"],
};

describe("the input as form fields", () => {
  it("reads each field the list can show, in the schema's order, and what it can't", () => {
    const rows = inputRows(SCHEMA);
    expect(rows.map((r) => (r.kind === "field" ? `${r.field.name}:${r.field.type}` : `${r.name}:other`))).toEqual([
      "site:text", "token:text", "floor:whole", "band:choice", "at:datetime", "tags:other", "code:other",
    ]);  // prettier-ignore
    expect(rows[1]).toEqual({
      kind: "field",
      field: { name: "token", label: "API token", type: "text", required: true, sensitive: true, description: "The ticketing system's token for this site.", values: [] },
    });
    expect(rows[3]).toMatchObject({ kind: "field", field: { values: ["2.4 GHz", "5 GHz"], default: "5 GHz" } });
    expect(rows[5]).toEqual({ kind: "other", name: "tags", required: false, what: "a list" });
    expect(rows[6]).toEqual({ kind: "other", name: "code", required: false, what: "text with rules of its own" });
  });

  it("changes one field and keeps every other key and field as written", () => {
    const next = setField(SCHEMA, "site", { label: "Site name", required: false });
    expect(next.properties).toEqual({ ...SCHEMA.properties, site: { type: "string", title: "Site name" } });
    expect(next.required).toEqual(["token"]);
    expect(Object.keys(next.properties as object)).toEqual(Object.keys(SCHEMA.properties));
    expect(setField(SCHEMA, "floor", { required: true }).required).toEqual(["site", "token", "floor"]);
    expect(setField(SCHEMA, "tags", { label: "x" })).toBe(SCHEMA); // the list can't show it: left as it is
  });

  it("drops a default a sensitive field can't have, and one its new type or values don't fit", () => {
    expect((setField(SCHEMA, "floor", { sensitive: true }).properties as Record<string, unknown>).floor).toEqual({ type: "integer", "x-sensitive": true });
    expect((setField(SCHEMA, "floor", { type: "number" }).properties as Record<string, unknown>).floor).toEqual({ type: "number", default: 0 });
    expect((setField(SCHEMA, "floor", { type: "text" }).properties as Record<string, unknown>).floor).toEqual({ type: "string" });
    expect((setField(SCHEMA, "band", { values: ["2.4 GHz", "6 GHz"] }).properties as Record<string, unknown>).band).toEqual({
      type: "string", enum: ["2.4 GHz", "6 GHz"],
    });  // prettier-ignore
    expect((setField(SCHEMA, "band", { type: "text" }).properties as Record<string, unknown>).band).toEqual({ type: "string", default: "5 GHz" });
    expect((setField(SCHEMA, "floor", { default: undefined }).properties as Record<string, unknown>).floor).toEqual({ type: "integer" });
    expect((setField(SCHEMA, "at", { type: "datetime", default: "2026-10-11T08:00:00Z" }).properties as Record<string, unknown>).at).toEqual({
      type: "string", format: "date-time", default: "2026-10-11T08:00:00Z",
    });  // prettier-ignore
  });

  it("renames a field in its place, its requirement following, and says when a name can't be one", () => {
    const next = renameField(SCHEMA, "site", "site_name");
    expect(Object.keys(next.properties as object)[0]).toBe("site_name");
    expect(next.required).toEqual(["site_name", "token"]);
    expect(nameProblem(SCHEMA, "site", "site")).toBeNull();
    expect(nameProblem(SCHEMA, "site", "token")).toBe("Another field has this name.");
    expect(nameProblem(SCHEMA, "site", "Site")).toMatch(/^Lowercase letters/);
    expect(nameProblem(SCHEMA, "site", "true")).toMatch(/^Lowercase letters/);
    expect(nameProblem(SCHEMA, "site", "rows")).toBe("`rows` and `row_count` are a CSV file's: declare the file, and its rows arrive there.");
  });

  it("adds an optional text field with a name not taken, and removes one with its requirement", () => {
    const { schema, name } = addField({ type: "object", properties: { field_2: {} } });
    expect(name).toBe("field_3");
    expect(schema.properties).toEqual({ field_2: {}, field_3: { type: "string" } });
    expect(addField({ type: "object" }).name).toBe("field_1");
    const removed = removeField(SCHEMA, "token");
    expect(removed.required).toEqual(["site"]);
    expect(Object.keys(removed.properties as object)).not.toContain("token");
    expect(removeField({ type: "object", properties: { a: {} }, required: ["a"] }, "a")).toEqual({ type: "object", properties: {} });
  });
});

describe("the fields' order (#144: stored JSON keeps no key order)", () => {
  const ABC = { type: "object", properties: { b: { type: "string" }, a: { type: "string" }, c: { type: "string" } } };

  it("lists the fields in the order the schema gives, the others after, as stored", () => {
    expect(fieldOrder({ ...ABC, "x-dewpoint-order": ["c", "a"] })).toEqual(["c", "a", "b"]);
    expect(inputRows({ ...ABC, "x-dewpoint-order": ["c", "a"] }).map((r) => (r.kind === "field" ? r.field.name : r.name))).toEqual(["c", "a", "b"]);
    expect(fieldOrder(ABC)).toEqual(["b", "a", "c"]);
  });

  it("reads an order that doesn't match the fields as far as it does (ruled: never refused)", () => {
    expect(fieldOrder({ ...ABC, "x-dewpoint-order": ["c", "zz", "a", "c", 7, null] })).toEqual(["c", "a", "b"]);
    for (const order of ["c", { c: 1 }, null, []]) expect(fieldOrder({ ...ABC, "x-dewpoint-order": order })).toEqual(["b", "a", "c"]);
  });

  it("keeps the order as written: a field added last, one renamed in its place, one removed gone", () => {
    const listed = { ...ABC, "x-dewpoint-order": ["c", "a", "b"] };
    expect(addField(listed).schema["x-dewpoint-order"]).toEqual(["c", "a", "b", "field_4"]);
    expect(addField(ABC).schema["x-dewpoint-order"]).toEqual(["b", "a", "c", "field_4"]); // a stored order written down
    expect(renameField(listed, "a", "alpha")["x-dewpoint-order"]).toEqual(["c", "alpha", "b"]);
    expect(removeField(listed, "a")["x-dewpoint-order"]).toEqual(["c", "b"]);
    expect(removeField({ type: "object", properties: { a: {} }, "x-dewpoint-order": ["a"] }, "a")).toEqual({ type: "object", properties: {} });
    expect(setField(listed, "a", { label: "A" })["x-dewpoint-order"]).toEqual(["c", "a", "b"]);
  });

  it("says a schema is a topic's shape whatever order its fields are listed in", () => {
    expect(sameSchema({ ...DEVICE_EVENTS, "x-dewpoint-order": ["topic", "events"] }, DEVICE_EVENTS)).toBe(true);
    expect(topicShaped({ ...DEVICE_EVENTS, "x-dewpoint-order": ["topic", "events"] }, MIST.topics)).toBe("device-events");
  });
});

describe("the draft's settings", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [], edges: [], settings: { declassify: [], input_schema: SCHEMA } };

  it("reads the input, an empty object schema when there's none", () => {
    expect(inputOf(doc)).toBe(SCHEMA);
    expect(inputOf({ graph_format: 1 })).toEqual({ type: "object" });
  });

  it("sets and removes settings keys, keeping the others", () => {
    const next = setSettings(doc, { input_schema: { type: "object" }, csv: undefined });
    expect(next.settings).toEqual({ declassify: [], input_schema: { type: "object" } });
    expect(setSettings({ graph_format: 1 }, { csv: { columns: [] } }).settings).toEqual({ csv: { columns: [] } });
  });
});

describe("a Mist event's shape", () => {
  it("knows the input is a topic's shape whatever its keys' order, and none when it isn't", () => {
    const reordered = { required: ["events", "topic"], $defs: DEVICE_EVENTS.$defs, properties: DEVICE_EVENTS.properties, type: "object" };
    expect(sameSchema(reordered, DEVICE_EVENTS)).toBe(true);
    expect(topicShaped(reordered, MIST.topics)).toBe("device-events");
    expect(topicShaped(SCHEMA, MIST.topics)).toBeNull();
  });

  it("lists the shape's own fields, then one event's, saying what may be missing", () => {
    const { rows, more } = shapeRows(DEVICE_EVENTS, "device-events", 4);
    expect(rows).toEqual([
      { path: "trigger.topic", what: "text, always device-events", optional: false },
      { path: "trigger.events", what: "list of device events", optional: false },
      { path: "[ ].ap_name", what: "text", optional: true },
      { path: "[ ].device_name", what: "text", optional: true },
      { path: "[ ].ev_type", what: "text", optional: true },
      { path: "[ ].mac", what: "text", optional: true },
    ]);
    expect(more).toBe(true);
    expect(shapeRows(DEVICE_EVENTS, "device-events").rows.at(-1)).toEqual({ path: "[ ].timestamp", what: "number", optional: false });
  });
});

describe("a choice from a connection (the 4f-3 design §5.7)", () => {
  const C1 = "00000000-0000-4000-8000-0000000000c1";
  const PICKER = { node: "acme.sites.get@1", field: "site_id", connection: C1 };
  const picked = (prop: Record<string, unknown>) => ({ type: "object", properties: { site: { type: "string", title: "Site", ...prop } }, required: ["site"] });

  it("reads a picker field, and one left unbound at import as a picker whose connection is empty", () => {
    expect(inputRows(picked({ "x-dewpoint-picker": PICKER }))).toEqual([
      { kind: "field", field: { name: "site", label: "Site", type: "picker", required: true, sensitive: false, description: "", values: [], picker: PICKER } },
    ]);
    const unbound = inputRows(picked({ "x-dewpoint-picker": { node: "acme.sites.get@1", field: "site_id" } }))[0]!;
    expect(unbound).toMatchObject({ kind: "field", field: { type: "picker", picker: { node: "acme.sites.get@1", field: "site_id", connection: null } } });
  });

  it("reads a picker beside a default, values, a format or sensitivity, or one that isn't a node and a field, read only", () => {
    for (const prop of [
      { "x-dewpoint-picker": PICKER, default: "s1" }, { "x-dewpoint-picker": PICKER, enum: ["s1"] }, { "x-dewpoint-picker": PICKER, format: "uuid" },
      { "x-dewpoint-picker": PICKER, "x-sensitive": false }, { "x-dewpoint-picker": { node: "acme.sites.get@1" } },
      { "x-dewpoint-picker": { ...PICKER, extra: 1 } }, { "x-dewpoint-picker": { ...PICKER, connection: 7 } }, { "x-dewpoint-picker": "acme" },
      { "x-dewpoint-picker": PICKER, type: "integer" },
    ]) expect(inputRows(picked(prop))[0]).toEqual({ kind: "other", name: "site", required: true, what: expect.stringContaining("with rules of its own") as string });  // prettier-ignore
  });

  it("writes a picker with no default, values or sensitivity, and removes it with its type", () => {
    const text = { type: "object", properties: { site: { type: "string", title: "Site", default: "HQ" } } };
    const made = setField(text, "site", { type: "picker", picker: PICKER });
    expect(made.properties).toEqual({ site: { type: "string", title: "Site", "x-dewpoint-picker": PICKER } });
    expect(setField(made, "site", { picker: { ...PICKER, connection: null } }).properties).toEqual({
      site: { type: "string", title: "Site", "x-dewpoint-picker": { node: "acme.sites.get@1", field: "site_id" } },
    });
    expect(setField(made, "site", { type: "text" }).properties).toEqual({ site: { type: "string", title: "Site" } });
    expect(setField(made, "site", { label: "Site name" }).properties).toEqual({ site: { type: "string", title: "Site name", "x-dewpoint-picker": PICKER } });
  });

  it("names the field a pointer is in, its name unescaped, or none outside the input's fields", () => {
    expect(inputFieldOf("/settings/input_schema/properties/site/x-dewpoint-picker")).toBe("site");
    expect(inputFieldOf("/settings/input_schema/properties/a~1b~0c")).toBe("a/b~c");
    expect(inputFieldOf("/settings/input_schema")).toBeNull();
    expect(inputFieldOf("/settings/failure_handler")).toBeNull();
  });
});
