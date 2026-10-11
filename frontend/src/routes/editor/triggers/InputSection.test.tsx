// SPDX-License-Identifier: Apache-2.0
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEVICE_EVENTS, MIST } from "../../../test/triggers";
import { STALE } from "../../../lib/unapplied";
import type { Diagnostic, GraphDoc, Validation } from "../../../lib/workflows";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

const SCHEMA = {
  type: "object",
  properties: { site: { type: "string", title: "Site" }, tags: { type: "array", items: { type: "string" } } },
  required: ["site"],
};
const draft = (settings: GraphDoc["settings"]): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings });
const input = () => screen.getByRole("region", { name: /^Input/ });
const checked = (diagnostics: Diagnostic[]): Validation => ({
  draft_revision: 1, valid: false, diagnostics, expressions: [], taint: { sites: [], declassified: [] }, conditional_steps: [], schedule_breaks: [],
});  // prettier-ignore
const problem = (field: string, code: string, message: string): Diagnostic => ({ code, severity: "error", message, fix: null, node: null, field });

beforeEach(() => {
  fakeApi({
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules: [] }),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings: [] }),
    "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ workflow_id: "w1", version_id: "v3", fields: [], csv: null }),
    "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: draft({ input_schema: SCHEMA }) }),
  });
});
afterEach(() => vi.restoreAllMocks());

describe("the input as form fields", () => {
  it("lists each field as the InputFields board does, and what the list can't show, read only", async () => {
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    const rows = within(input()).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows[0]).toContain("site · Site · Text · required");
    expect(rows[1]).toContain("tags · a list · read only here");
    expect(within(input()).getByRole("button", { name: "Edit site" })).toBeTruthy();
    expect(within(input()).queryByRole("button", { name: "Edit tags" })).toBeNull();
    expect(input().textContent).toContain("A field the list can't show (a list, an object of fields) appears read only: Edit as JSON changes it.");
  });

  it("adds a field and edits it, each control's typing one undo step", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "＋ Field" }));
    const field = within(input()).getByRole("group", { name: "The field field_3" });
    await userEvent.type(within(field).getByRole("textbox", { name: "Label" }), "Note");
    expect(panel.settings()?.input_schema).toMatchObject({ properties: { field_3: { type: "string", title: "Note" } } });
    expect(new Set(panel.writes.slice(1).map((w) => w.mark))).toEqual(new Set(["/settings/input_schema/properties/field_3/title"]));
    await userEvent.selectOptions(within(field).getByRole("combobox", { name: "Type" }), "Yes or no");
    await userEvent.click(within(field).getByRole("checkbox", { name: "Required" }));
    expect(panel.settings()?.input_schema).toMatchObject({ properties: { field_3: { type: "boolean", title: "Note" } }, required: ["site", "field_3"] });
  });

  it("holds a name until it can be one, and applies it when focus leaves it", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    const name = within(input()).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Site");
    fireEvent.blur(name);
    expect(input().textContent).toContain("Lowercase letters, digits and _, starting with a letter; not in, true, false or null.");
    expect(Object.keys((panel.settings()?.input_schema as { properties: object }).properties)).toEqual(["site", "tags"]);
    await userEvent.clear(name);
    await userEvent.type(name, "site_name{Enter}");
    expect(Object.keys((panel.settings()?.input_schema as { properties: object }).properties)).toEqual(["site_name", "tags"]);
    expect(within(input()).getByRole("group", { name: "The field site_name" })).toBeTruthy(); // still open, on its new name
    expect(panel.held()).toEqual([]);
  });

  it("holds a number's default that doesn't parse, and writes one that does", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object", properties: { floor: { type: "integer" } } } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit floor" }));
    const value = within(input()).getByRole("textbox", { name: "Default" });
    await userEvent.type(value, "2.5");
    expect(input().textContent).toContain("A whole number, like 42.");
    expect(panel.held()).toHaveLength(1);
    await userEvent.clear(value);
    await userEvent.type(value, "3");
    expect(panel.settings()?.input_schema).toEqual({ type: "object", properties: { floor: { type: "integer", default: 3 } } });
    expect(panel.held()).toEqual([]);
  });

  it("gives a sensitive field no default and no Choice: either would be written into the workflow", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object", properties: { token: { type: "string", default: "x" } } } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit token" }));
    await userEvent.click(within(input()).getByRole("checkbox", { name: "Sensitive" }));
    expect(panel.settings()?.input_schema).toEqual({ type: "object", properties: { token: { type: "string", "x-sensitive": true } } });
    expect(within(input()).getByRole<HTMLInputElement>("textbox", { name: "Default" }).disabled).toBe(true);
    expect(within(input()).getByRole<HTMLOptionElement>("option", { name: "Choice" }).disabled).toBe(true);
  });

  it("gives focus back to a field's Edit once its editor closes, by Done or Escape, and to ＋ Field once it's removed", async () => {
    // The review of revision 1: Done left focus on the page's body.
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    const edit = () => within(input()).getByRole("button", { name: "Edit site" });
    await userEvent.click(edit());
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(edit()));
    await userEvent.click(edit());
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() => expect(document.activeElement).toBe(edit()));
    await userEvent.click(edit());
    await userEvent.click(within(input()).getByRole("button", { name: "Remove field" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "＋ Field" })));
  });

  it("keeps a renamed field's editor as it is: Tab moves on from its name, and one click on Done closes it", async () => {
    // The review of revision 2: the rename remounted the editor, Tab landed back on Name, and Done's first click was lost.
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    const name = () => within(input()).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name());
    await userEvent.type(name(), "where");
    await userEvent.tab();
    expect(Object.keys(panel.settings()?.input_schema?.properties as object)).toEqual(["where", "tags"]);
    expect(document.activeElement).toBe(within(input()).getByRole("textbox", { name: "Label" }));
    await userEvent.clear(name());
    await userEvent.type(name(), "place");
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    expect(Object.keys(panel.settings()?.input_schema?.properties as object)).toEqual(["place", "tags"]);
    expect(within(input()).queryByRole("group", { name: /^The field / })).toBeNull();
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit place" })));
  });

  it("shows the server's problems at their field", async () => {
    await showPanel({
      doc: draft({ input_schema: { type: "object", properties: { rows: { type: "string" } } } }),
      check: checked([problem("/settings/input_schema/properties/rows", "settings.reserved_name", "`rows` and `row_count` are a CSV's.")]),
    });
    expect(within(input()).getAllByRole("listitem")[0]!.textContent).toContain("`rows` and `row_count` are a CSV's.");
  });
});

describe("the input from a Mist event", () => {
  it("copies a topic's shape into the draft, read only, then gives it back to form fields", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(await within(input()).findByRole("button", { name: "Use a Mist event…" }));
    expect(input().textContent).toContain("This replaces the input's 2 fields with the event's shape. Undo brings them back.");
    await userEvent.type(within(input()).getByRole("searchbox", { name: "Find a topic" }), "device");
    expect(within(input()).getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["device-events", "device-updowns"]);
    await userEvent.click(within(input()).getByRole("radio", { name: "device-events" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Use device-events" }));
    expect(panel.settings()?.input_schema).toEqual(DEVICE_EVENTS);
    expect(input().textContent).toContain("A Mist event: device-events");
    expect(within(input()).getByRole("list", { name: "The event's shape" }).textContent).toContain("[ ].ap_name");
    await userEvent.click(within(input()).getByRole("button", { name: "Use form fields instead" }));
    expect(panel.settings()?.input_schema).toEqual({ type: "object", properties: {} });
  });

  it("gives focus back to what opened the picker, and to what replaces each choice", async () => {
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    const open = await within(input()).findByRole("button", { name: "Use a Mist event…" });
    await userEvent.click(open);
    await userEvent.click(within(input()).getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Use a Mist event…" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Use a Mist event…" }));
    await userEvent.click(within(input()).getByRole("radio", { name: "alarms" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Use alarms" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Use another event…" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Use form fields instead" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "＋ Field" })));
  });
});

describe("the input's CSV file", () => {
  it("adds one of one column, holds a header a save wouldn't take, and removes it whole", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object" } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "＋ CSV file" }));
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "Column 1", name: "column_1", type: "string" }] });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit Column 1" }));
    const column = within(input()).getByRole("group", { name: "The column Column 1" });
    expect(within(column).getByRole<HTMLButtonElement>("button", { name: "Remove column" }).disabled).toBe(true);
    const header = within(column).getByRole("textbox", { name: "Header in the file" });
    await userEvent.clear(header);
    expect(column.textContent).toContain("A header is from 1 to 200 characters.");
    await userEvent.type(header, "AP name");
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "AP name", name: "column_1", type: "string" }] });
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove the CSV file" }));
    expect(panel.settings()?.csv).toBeUndefined();
  });

  it("offers a required column's default its two fixes, from the server's problem", async () => {
    const csv = { columns: [{ header: "Floor", name: "floor", type: "integer" as const, required: true, default: 0 }] };
    const message = "A required column takes no default: an empty cell is refused, so the default would never apply.";
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object" }, csv }), check: checked([problem("/settings/csv/columns/0/default", "csv.required_default", message)]) });
    expect(input().textContent).toContain(`Floor: ${message}`);
    await userEvent.click(within(input()).getAllByRole("button", { name: "Edit Floor" })[0]!); // its row's, or its problem's: one action
    await userEvent.click(within(input()).getByRole("button", { name: "Make it optional" }));
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "Floor", name: "floor", type: "integer", required: false, default: 0 }] });
  });

  it("never writes a header typed for a column whose place another took since, until Apply here or Discard", async () => {
    // The review of revision 1: B's header held, A removed, then the text at that place finished: it renamed C.
    const columns = ["A", "B", "C"].map((h) => ({ header: h, name: h.toLowerCase(), type: "string" as const }));
    const panel = await showPanel({ doc: draft({ csv: { columns } }) });
    const header = () => within(input()).getByRole<HTMLInputElement>("textbox", { name: "Header in the file" });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit B" }));
    await userEvent.clear(header());
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove column" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit C" }));
    expect(input().textContent).toContain(STALE);
    await userEvent.type(header(), "X");
    expect(panel.settings()?.csv?.columns.map((c) => c.header)).toEqual(["B", "C"]);
    await userEvent.click(within(input()).getByRole("button", { name: "Discard the edit to Column 2's header" }));
    expect(panel.held()).toEqual([]);
    expect(header().value).toBe("C");
    await userEvent.type(header(), "2");
    expect(panel.settings()?.csv?.columns.map((c) => c.header)).toEqual(["B", "C2"]);
  });

  it("never writes a default typed for a column whose place a column of another type took since", async () => {
    // The review of revision 2: B's whole-number default held, A removed, then finished at that place in text column C.
    const columns = [
      { header: "A", name: "a", type: "integer" as const }, { header: "B", name: "b", type: "integer" as const }, { header: "C", name: "c", type: "string" as const },
    ];  // prettier-ignore
    const panel = await showPanel({ doc: draft({ csv: { columns } }) });
    const value = () => within(input()).getByRole<HTMLInputElement>("textbox", { name: "Default (an empty cell gets it)" });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit B" }));
    await userEvent.type(value(), "9x");
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove column" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit C" }));
    expect(value().value).toBe("9x");
    expect(input().textContent).toContain(STALE);
    await userEvent.clear(value());
    await userEvent.type(value(), "9");
    expect(panel.settings()?.csv?.columns[1]).toEqual({ header: "C", name: "c", type: "string" });
    await userEvent.click(within(input()).getByRole("button", { name: "Discard the edit to Column 2's default" }));
    await userEvent.type(value(), "9");
    expect(panel.settings()?.csv?.columns[1]).toEqual({ header: "C", name: "c", type: "string", default: "9" });
  });

  it("gives focus to a column's first control when it opens, back to its Edit when it closes, and to ＋ Column once it's removed", async () => {
    const columns = ["A", "B"].map((h) => ({ header: h, name: h.toLowerCase(), type: "string" as const }));
    await showPanel({ doc: draft({ csv: { columns } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit B" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("textbox", { name: "Header in the file" })));
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit B" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit A" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove column" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "＋ Column" })));
  });

  it("holds most rows past the platform's, and writes a lower one", async () => {
    const panel = await showPanel({ doc: draft({ csv: { columns: [{ header: "A", name: "a", type: "string" }] } }) });
    const rows = within(input()).getByRole("textbox", { name: "Most rows" });
    await userEvent.type(rows, "20000");
    expect(input().textContent).toContain("A whole number from 1 to 10,000.");
    await userEvent.clear(rows);
    await userEvent.type(rows, "500");
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "A", name: "a", type: "string" }], max_rows: 500 });
  });
});

describe("the input as JSON", () => {
  it("writes text that reads, holds text that doesn't with its line, and shows the server's problems at theirs", async () => {
    const csv = { columns: [{ header: "Floor", name: "floor", type: "integer" as const, required: true, default: 0 }] };
    const panel = await showPanel({
      doc: draft({ input_schema: { type: "object" }, csv }),
      check: checked([problem("/settings/csv/columns/0/default", "csv.required_default", "A required column takes no default.")]),
    });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    const box = within(input()).getByRole<HTMLTextAreaElement>("textbox", { name: "The input's schema and CSV columns" });
    const line = box.value.split("\n").findIndex((l) => l.includes('"default": 0')) + 1;
    expect(input().textContent).toContain(`Line ${line}, csv.columns[0].default: A required column takes no default.`);
    fireEvent.change(box, { target: { value: '{"input_schema": {"type": "object", "properties": {"a": {"type": "string"}}}}' } });
    expect(panel.settings()).toEqual({ input_schema: { type: "object", properties: { a: { type: "string" } } } });
    fireEvent.change(box, { target: { value: '{\n"input_schema": {,\n}' } });
    expect(input().textContent).toContain("Line 2: This isn't valid JSON, so it isn't saved.");
    expect(panel.held().map((u) => u.pointer)).toEqual(["/settings/input"]);
    await userEvent.click(within(input()).getByRole("button", { name: "Discard what isn't saved" }));
    expect(panel.held()).toEqual([]);
    expect(JSON.parse(box.value)).toEqual({ input_schema: { type: "object", properties: { a: { type: "string" } } } });
  });
});

describe("the input as JSON, typed over what changed since", () => {
  const box = () => within(input()).getByRole<HTMLTextAreaElement>("textbox", { name: "The input's schema and CSV columns" });

  it("takes focus when it opens, and gives it back to Edit as JSON when it closes", async () => {
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(box()));
    await userEvent.click(within(input()).getByRole("button", { name: "Back to the fields" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit as JSON" })));
  });

  it("never writes JSON typed over an input that changed since, until Apply here", async () => {
    // The review of revision 1: JSON held, a field added, then the JSON finished: the new field was gone.
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    fireEvent.change(box(), { target: { value: '{"input_schema": {"type": "object"' } });
    await userEvent.click(within(input()).getByRole("button", { name: "Back to the fields" }));
    await userEvent.click(within(input()).getByRole("button", { name: "＋ Field" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    expect(input().textContent).toContain(STALE);
    fireEvent.change(box(), { target: { value: '{"input_schema": {"type": "object"}}' } });
    expect(Object.keys(panel.settings()?.input_schema?.properties as object)).toEqual(["site", "tags", "field_3"]);
    expect(input().textContent).toContain(STALE);
    await userEvent.click(within(input()).getByRole("button", { name: "Apply here: The input as JSON" }));
    expect(panel.settings()?.input_schema).toEqual({ type: "object" });
    expect(panel.held()).toEqual([]);
  });

  it("discards JSON typed over an input that changed since, showing the input as it is", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    fireEvent.change(box(), { target: { value: "{" } });
    panel.replace(draft({ input_schema: { type: "object" } })); // an undo, under it
    await userEvent.click(within(input()).getByRole("button", { name: "Discard the edit to The input as JSON" }));
    expect(panel.held()).toEqual([]);
    expect(JSON.parse(box().value)).toEqual({ input_schema: { type: "object" } });
    await vi.waitFor(() => expect(document.activeElement).toBe(box()));
  });
});

it("shows the input read only to a viewer, as JSON too", async () => {
  await showPanel({ doc: draft({ input_schema: SCHEMA }), editable: false, viewer: true });
  expect(within(input()).queryByRole("button", { name: "Edit site" })).toBeNull();
  expect(within(input()).queryByRole("button", { name: "＋ Field" })).toBeNull();
  await userEvent.click(within(input()).getByRole("button", { name: "Show as JSON" }));
  expect(within(input()).getByRole<HTMLTextAreaElement>("textbox", { name: "The input's schema and CSV columns" }).readOnly).toBe(true);
});
