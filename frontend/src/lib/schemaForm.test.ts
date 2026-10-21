// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { CREATE, DELAY, DEVICE_UPDATE, FILTER, IF, LOOP, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith, UPDATE } from "../test/nodeTypes";
import {
  branchesOf, canFixed, canFormula, changeParts, emptyOf, entryOf, fieldLabel, fieldsOf, isReadOnly, itemOf, kindOf, offeredOf,
  pointerOf, propertiesOf, settingsOf, startsAsFormula, tabsOf, takesPills, unionTitle,
} from "./schemaForm";  // prettier-ignore

const field = (type: Parameters<typeof fieldsOf>[0], name: string) => fieldsOf(type).find((f) => f.name === name)!;

describe("fieldsOf", () => {
  it("reads each top-level property as a field, in the schema's order, labelled by its title", () => {
    expect(fieldsOf(REMOTE).map((f) => [f.name, f.label, f.widget, f.required])).toEqual([
      ["connection", "Connection", "connection", true],
      ["site_id", "Site", "options", true],
      ["token", "Token", "text", false],
      ["query", "Query", "group", false],
      ["mode", "Mode", "enum", false],
      ["when", "When", "datetime", false],
      ["tags", "Tags", "list", false],
      ["note", "Note", "text", false],
    ]);
  });

  it("chooses a formula for x-widget cel, a workflow picker for run_workflow, and a map for an open object", () => {
    expect(field(IF, "condition").widget).toBe("formula");
    expect(field(IF, "condition").base).toBe("boolean"); // the control for a fixed value
    expect(fieldsOf(RUN_WORKFLOW).map((f) => f.widget)).toEqual(["workflow", "map"]);
    expect(field(TRANSFORM, "fields").widget).toBe("map");
    expect(field(DELAY, "duration_s").widget).toBe("integer");
    expect(field(LOOP, "collect").widget).toBe("json"); // untyped
  });

  it("falls back to the type's widget for a plugin widget it doesn't have", () => {
    const blocks = typeWith({
      type: "object",
      properties: { blocks: { type: "array", items: { type: "object", properties: { text: { type: "string" } } }, "x-widget": "message-blocks" } },
    });  // prettier-ignore
    expect(fieldsOf(blocks)[0]!.widget).toBe("list");
  });

  it("follows $ref, drops a null branch, and labels a list's item by its place", () => {
    const item = itemOf(field(SWITCH, "cases"), 0);
    expect([item.widget, item.label, item.pointer]).toEqual(["group", "Cases, item 1", "/cases/0"]);
    expect(propertiesOf(item).map((f) => [f.name, f.widget, f.port, f.literalOnly])).toEqual([
      ["port", "text", true, true],
      ["when", "formula", false, false],
    ]);
    expect(field(REMOTE, "note").schema.type).toBe("string");
  });

  it("names each field by the JSON pointer the server's problems use", () => {
    expect(pointerOf(["fields", "a/b~c", 0])).toBe("/fields/a~1b~0c/0");
    expect(propertiesOf(field(REMOTE, "query"))[0]!.pointer).toBe("/query/limit");
    expect(entryOf(field(TRANSFORM, "fields"), "total").pointer).toBe("/fields/total");
  });

  it("hints a field's description, its default and a date's format, never a sensitive default", () => {
    expect(propertiesOf(field(REMOTE, "query"))[0]!.hint).toBe("How many to list. If empty: 100.");
    expect(field(REMOTE, "when").hint).toBe("A date and time in ISO 8601, like 2026-10-08T09:00:00Z.");
    const secret = typeWith({ type: "object", properties: { key: { type: "string", default: "s3cr3t", "x-sensitive": true } } });
    expect(fieldsOf(secret)[0]!.hint).toBeNull();
  });

  it("hints no default that holds a sensitive part", () => {
    const holder = typeWith({
      type: "object",
      properties: { auth: { type: "object", default: { key: "s3cr3t" }, properties: { key: { type: "string", "x-sensitive": true } } } },
    });  // prettier-ignore
    expect(fieldsOf(holder)[0]!.hint).toBeNull();
  });

  it("shows a schema that repeats itself, or one nested too deep, as JSON", () => {
    const tree = typeWith({
      $defs: { Node: { type: "object", properties: { name: { type: "string" }, child: { $ref: "#/$defs/Node" } } } },
      type: "object", properties: { root: { $ref: "#/$defs/Node" } },
    });  // prettier-ignore
    const root = fieldsOf(tree)[0]!;
    expect([root.widget, root.cut]).toEqual(["group", false]);
    const child = propertiesOf(root).find((f) => f.name === "child")!;
    expect([child.widget, child.base, child.cut]).toEqual(["json", "json", true]); // never a group within a group within…
    const nest = (n: number): Record<string, unknown> => (n === 0 ? { type: "string" } : { type: "object", properties: { x: nest(n - 1) } });
    let deep = fieldsOf(typeWith({ type: "object", properties: { a: nest(9) } }))[0]!;
    for (let i = 0; i < 7; i++) deep = propertiesOf(deep)[0]!;
    expect([deep.path.length, deep.cut]).toEqual([8, false]);
    expect(propertiesOf(deep)[0]!.cut).toBe(true); // the 9th part down
  });
});

it("puts the required fields on Setup and the rest on Options", () => {
  const { setup, options } = tabsOf(fieldsOf(LOOP));
  expect(setup.map((f) => f.name)).toEqual(["items"]);
  expect(options.map((f) => f.name)).toEqual(["concurrency", "item_cap", "on_item_error", "collect"]);
});

describe("the kinds of value a field takes", () => {
  it("takes a fixed value only where x-dewpoint-literal is on the path", () => {
    const concurrency = field(LOOP, "concurrency");
    expect([canFixed(concurrency), canFormula(concurrency)]).toEqual([true, false]);
    expect(canFormula(propertiesOf(itemOf(field(SWITCH, "cases"), 0))[0]!)).toBe(false);
  });

  it("takes no formula for a whole that holds a literal-only part", () => {
    expect(canFormula(field(SWITCH, "cases"))).toBe(false);
    expect(canFormula(itemOf(field(SWITCH, "cases"), 0))).toBe(false);
  });

  it("takes neither a fixed value nor a formula where the engine takes only references", () => {
    const source = fieldsOf(typeWith({ type: "object", properties: { source: { type: "string", "x-dewpoint-kinds": ["ref", "template"] } } }))[0]!;
    expect([canFixed(source), canFormula(source)]).toEqual([false, false]);
  });

  it("follows x-dewpoint-kinds: a predicate takes only a formula", () => {
    const predicate = field(FILTER, "predicate");
    expect([canFixed(predicate), canFormula(predicate), startsAsFormula(predicate)]).toEqual([false, true, true]);
  });

  it("takes no fixed value in a sensitive field, and knows a whole that holds one", () => {
    const token = field(REMOTE, "token");
    expect([canFixed(token), canFormula(token)]).toEqual([false, true]);
    const holder = typeWith({ type: "object", properties: { auth: { type: "object", properties: { key: { type: "string", "x-sensitive": true } } } } });
    expect(fieldsOf(holder)[0]!.holdsSensitive).toBe(true);
    expect(field(REMOTE, "query").holdsSensitive).toBe(false);
  });

  it("starts a condition, an untyped value and JSON as a formula, and a text as a fixed value", () => {
    expect(startsAsFormula(field(IF, "condition"))).toBe(true);
    expect(startsAsFormula(entryOf(field(TRANSFORM, "fields"), "x"))).toBe(true);
    expect(startsAsFormula(field(LOOP, "items"))).toBe(true);
    expect(startsAsFormula(field(REMOTE, "site_id"))).toBe(false);
  });
});

it("empties a property by removing it, and a list's item or a map's entry by blanking it", () => {
  expect(emptyOf(field(REMOTE, "tags"))).toBeUndefined();
  expect(emptyOf(itemOf(field(REMOTE, "tags"), 0))).toBe("");
  expect(emptyOf(entryOf(field(TRANSFORM, "fields"), "x"))).toBeNull();
});

it("finds a sensitive part under patternProperties or propertyNames, as the engine does (the final review)", () => {
  const marked = (inner: Record<string, unknown>) =>
    fieldsOf(typeWith({ type: "object", properties: { headers: { type: "object", title: "Headers", ...inner } } }))[0]!;
  // engine/sensitive.py: every pattern's schema, matched or not; a map whose keys are sensitive is sensitive whole.
  expect(marked({ patternProperties: { "^x-": { type: "string", "x-sensitive": true } } }).holdsSensitive).toBe(true);
  expect(marked({ propertyNames: { type: "string", "x-sensitive": true } }).holdsSensitive).toBe(true);
  expect(marked({ patternProperties: { "^x-": { type: "string" } } }).holdsSensitive).toBe(false);
});

describe("4c-2b's field kinds", () => {
  const fields = (schema: Record<string, unknown>) => fieldsOf(typeWith({ type: "object", properties: schema }));
  it("takes text with data pills in a text field the engine lets template, never a secret, a choice or a formula", () => {
    const [text, secret, choice, cel, refs, plain] = fields({
      text: { type: "string" },
      secret: { type: "string", "x-sensitive": true },
      choice: { type: "string", enum: ["a", "b"] },
      cel: { type: "boolean", "x-widget": "cel" },
      refs: { type: "string", "x-dewpoint-kinds": ["ref", "template"] },
      plain: { type: "string", "x-dewpoint-kinds": ["literal"] },
    });
    expect([text, secret, choice, cel, refs, plain].map((f) => takesPills(f!))).toEqual([true, false, false, false, true, false]);
  });
  it("takes data pills in a field with live choices (4f-2), never a literal-only one", () => {
    const type = typeWith(
      { type: "object", properties: { site: { type: "string" }, fixed: { type: "string", "x-dewpoint-literal": true } } },
      { options: ["site", "fixed"] },
    );
    expect(fieldsOf(type).map((f) => [f.widget, takesPills(f)])).toEqual([["options", true], ["options", false]]);
  });
  it("labels a field by its parts' labels", () => {
    expect(fieldLabel(SWITCH, "/cases/1/when")).toBe("Cases, item 2 › Condition");
    expect(fieldLabel(IF, "/condition")).toBe("Condition");
    expect(fieldLabel(IF, "/nope")).toBe("/nope");
  });
});

describe("4f-2b's changes", () => {
  const names = (fs: { name: string }[]) => fs.map((f) => f.name);
  it("draws an update's body, mode and clear together on Setup, after its required fields", () => {
    const { setup, changes, options } = settingsOf(UPDATE, fieldsOf(UPDATE));
    expect(names(setup)).toEqual(["connection", "thing_id"]);
    expect(changes?.widget).toBe("update");
    expect(names(changeParts(changes!))).toEqual(["body", "mode", "clear"]);
    expect(options).toEqual([]);
  });
  it("draws a create's body as its settings", () => {
    const { setup, changes } = settingsOf(CREATE, fieldsOf(CREATE));
    expect(names(setup)).toEqual(["connection"]);
    expect([changes?.widget, changes?.mode, changes?.clear]).toEqual(["create", null, null]);
    expect(names(changeParts(changes!))).toEqual(["body"]);
  });
  it("leaves an update without what the changes need to the generic form", () => {
    const schema = UPDATE.config_schema as Record<string, Record<string, unknown>>;
    const properties = Object.fromEntries(Object.entries(schema.properties!).filter(([name]) => name !== "clear"));
    const odd = typeWith({ ...schema, properties });
    const { changes, options } = settingsOf(odd, fieldsOf(odd));
    expect(changes).toBeNull();
    expect(names(options)).toEqual(["body", "mode"]);
  });
  it("offers a group's settings without the ones Mist sets", () => {
    const body = fieldsOf(UPDATE).find((f) => f.name === "body")!;
    expect(names(offeredOf(body))).toEqual(["name", "enabled", "rogue", "auto_upgrade", "port_usages", "networks", "tags", "vlan_id", "api_secret", "radius"]);
    expect(isReadOnly(propertiesOf(body).find((p) => p.name === "id")!)).toBe(true);
    expect(branchesOf(body)).toEqual([]);
  });
  it("reads a union body's branches, their kind and the union's own title", () => {
    const body = fieldsOf(DEVICE_UPDATE).find((f) => f.name === "body")!;
    const branches = branchesOf(body);
    expect(branches.map((b) => [b.label, b.pointer])).toEqual([["Camera", "/body"], ["Sensor", "/body"]]);
    expect(body.label).toBe("Body");
    expect(unionTitle(body)).toBe("Device");
    expect(kindOf(branches)).toEqual({ name: "type", values: ["camera", "sensor"] });
    expect(names(offeredOf(branches[0]!, "type"))).toEqual(["name", "notes", "zoom"]);
    expect(propertiesOf(branches[1]!).map((p) => p.pointer)).toEqual(["/body/type", "/body/name", "/body/notes", "/body/range"]);
  });
});
