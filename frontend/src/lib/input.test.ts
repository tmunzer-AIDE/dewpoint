// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { DEVICE_EVENTS, MIST } from "../test/triggers";
import {
  addField, inputOf, inputRows, nameProblem, removeField, renameField, sameSchema, setField, setSettings, shapeRows, topicShaped,
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
