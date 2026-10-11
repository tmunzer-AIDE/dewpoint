// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { CsvSettings } from "./csv";
import { inputText, lineOf, pointerLines, pointerWords, readInput } from "./inputJson";
import type { GraphDoc } from "./workflows";

const SCHEMA = { type: "object", properties: { change: { type: "string", title: "Change ticket" } }, required: ["change"] };
const CSV: CsvSettings = {
  columns: [{ header: "AP name", name: "ap_name", type: "string", required: true }, { header: "Floor", name: "floor", type: "integer", required: true, default: 0 }],
};
const doc = (settings: GraphDoc["settings"]): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings });

describe("the input as JSON text", () => {
  it("shows the input schema, and the CSV file only when one is declared", () => {
    expect(JSON.parse(inputText(doc({ input_schema: SCHEMA })))).toEqual({ input_schema: SCHEMA });
    expect(JSON.parse(inputText(doc({ input_schema: SCHEMA, csv: CSV })))).toEqual({ input_schema: SCHEMA, csv: CSV });
    expect(JSON.parse(inputText({ graph_format: 1 }))).toEqual({ input_schema: { type: "object" } });
  });

  it("reads text a save takes back as the input, a null csv as none", () => {
    const text = JSON.stringify({ input_schema: SCHEMA, csv: CSV });
    expect(readInput(text)).toEqual({ value: { input_schema: SCHEMA, csv: CSV } });
    expect(readInput(JSON.stringify({ input_schema: SCHEMA, csv: null }))).toEqual({ value: { input_schema: SCHEMA } });
  });

  it("says why text isn't saved: where it breaks, what it must hold, what the save would refuse", () => {
    expect(readInput('{\n  "input_schema": {\n    "type": "object",\n  }\n}')).toEqual({ problem: "This isn't valid JSON, so it isn't saved.", line: 4 });
    expect(readInput("[]")).toEqual({ problem: "It holds `input_schema`, an object, and optionally `csv`.", line: null });
    expect(readInput('{"input_schema": {}, "vars": {}}')).toMatchObject({ line: null });
    expect(readInput('{"input_schema": {}, "csv": {"columns": []}}')).toEqual({ problem: "A CSV file has from 1 to 200 columns.", line: null });
    expect(readInput('{"input_schema": {"default": 1e400}}')).toEqual({ problem: "A number here is too large to keep, so it isn't saved.", line: null });
  });
});

describe("where a server's problem shows in the text", () => {
  const text = inputText(doc({ input_schema: SCHEMA, csv: CSV }));

  it("names a settings pointer as a reader says it", () => {
    expect(pointerWords("/settings/csv/columns/1/default")).toBe("csv.columns[1].default");
    expect(pointerWords("/settings/input_schema/properties/a~1b")).toBe("input_schema.properties.a/b");
    expect(pointerWords("/settings/input_schema")).toBe("input_schema");
  });

  it("finds the line each value starts on, and the nearest one the text has", () => {
    const lines = pointerLines(text);
    const at = (needle: string) => text.split("\n").findIndex((l) => l.includes(needle)) + 1;
    expect(lines.get("")).toBe(1);
    expect(lines.get("/input_schema/properties/change/title")).toBe(at('"Change ticket"'));
    expect(lines.get("/csv/columns/1")).toBe(at('"header": "Floor"') - 1);
    expect(lineOf(text, "/settings/csv/columns/1/default")).toBe(at('"default": 0'));
    expect(lineOf(text, "/settings/csv/columns/1/values")).toBe(at('"header": "Floor"') - 1); // not in the text: its column
    expect(lineOf(text, "/settings/vars_schema")).toBe(1);
  });

  it("reads text laid out any way, escapes and all", () => {
    const odd = '{"input_schema":{"properties":{"a/b":{"title":"q\\"x"}},"required":[]},\n"csv":{"columns":[{"header":"H","name":"h","type":"string"}]}}';
    expect(lineOf(odd, "/settings/input_schema/properties/a~1b/title")).toBe(1);
    expect(lineOf(odd, "/settings/csv/columns/0/name")).toBe(2);
  });
});
