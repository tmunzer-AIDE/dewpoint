// SPDX-License-Identifier: Apache-2.0
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Diagnostic, GraphDoc, Validation } from "../../../lib/workflows";
import { LISTING } from "../../../test/nodeTypes";
import { MIST } from "../../../test/triggers";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

// The Authoring board's field, on a made-up service's lists (D24): a site picked from Acme Prod's sites.
const C1 = "00000000-0000-4000-8000-0000000000c1";
const C2 = "00000000-0000-4000-8000-0000000000c2";
const C3 = "00000000-0000-4000-8000-0000000000c3";
const connection = (id: string, name: string, type: string, status: string) => ({
  id, name, type, status, revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
});  // prettier-ignore
const CONNECTIONS = [connection(C1, "Acme Prod", "acme", "ok"), connection(C2, "Acme Lab", "acme", "unverified"), connection(C3, "Slack ops", "slack", "ok")];
const PICKER = { node: "acme.site_zones.get@1", field: "site_id", connection: C1 };
const draft = (site: Record<string, unknown>): GraphDoc =>
  ({ graph_format: 1, nodes: [], edges: [], settings: { input_schema: { type: "object", properties: { site: { type: "string", title: "Site", ...site } }, required: ["site"] } } });  // prettier-ignore
const input = () => screen.getByRole("region", { name: /^Input/ });
const field = () => within(input()).getByRole("group", { name: "The field site" });
const select = (name: string) => within(field()).getByRole<HTMLSelectElement>("combobox", { name });
const site = (settings: GraphDoc["settings"]) => (settings?.input_schema as { properties: { site: unknown } }).properties.site;

const OPTIONS = "POST /api/v1/t/t1/node-types/acme.site_zones.get@1/options";
let connections: unknown[];
let listConnections: () => Response | Promise<Response>;
let sent: { method: string; path: string; body: unknown }[];
beforeEach(() => {
  connections = CONNECTIONS;
  listConnections = () => json(connections);
  sent = fakeApi({
    [OPTIONS]: () => json({ options: [{ value: "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d", label: "Lyon DC" }, { value: "s2", label: "Lyon store 4" }] }),
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/node-types": () => json(LISTING),
    "GET /api/v1/t/t1/connections": () => listConnections(),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules: [] }),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings: [] }),
  });
});
afterEach(() => vi.restoreAllMocks());

describe("a Choice from a connection, authored (the 4f-3 design §5.7; the Authoring board)", () => {
  it("is held with no list or connection, the field saved as plain text meanwhile, with no default, values or sensitivity", async () => {
    const panel = await showPanel({ doc: draft({ default: "HQ" }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    await userEvent.selectOptions(select("Type"), "Choice from a connection");
    expect(site(panel.settings())).toEqual({ type: "string", title: "Site" });
    expect(select("Type").value).toBe("picker");
    expect([...select("Its choices").options].map((o) => o.text)).toEqual(["Choose a list", "Acme · Org PSKs", "Acme · Org sites", "Acme · Org WLANs"]);
    const connection = select("Connection");
    expect(connection.disabled).toBe(true);
    expect([...connection.options].map((o) => o.text)).toEqual(["Choose the list first"]);
    expect(within(field()).getByText("Until a list and a connection are chosen, the field is saved as plain text.")).toBeTruthy();
    for (const gone of ["Default", "Sensitive"]) expect(within(field()).queryByLabelText(gone)).toBeNull();
  });

  it("writes the picker in one step once both are chosen, naming the list's read-only step, its connection of that kind", async () => {
    const panel = await showPanel({ doc: draft({}) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    await userEvent.selectOptions(select("Type"), "Choice from a connection");
    const before = panel.writes.length;
    await userEvent.selectOptions(select("Its choices"), "Acme · Org sites");
    expect(panel.writes).toHaveLength(before); // a list alone isn't written
    expect([...select("Connection").options].map((o) => o.text)).toEqual(["Choose a connection", "Acme Prod · verified", "Acme Lab · not verified yet"]);
    await userEvent.selectOptions(select("Connection"), "Acme Prod · verified");
    expect(site(panel.settings())).toEqual({ type: "string", title: "Site", "x-dewpoint-picker": PICKER });
    expect(panel.writes.slice(before)).toEqual([{ mark: "/settings/input_schema/properties/site/x-dewpoint-picker", said: null }]);
    expect(within(field()).getByText("The list the form shows; the field holds the picked one's ID.")).toBeTruthy();
  });

  it("rewrites the picker when either changes, and another type removes it", async () => {
    const panel = await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    expect(select("Its choices").value).toBe("site_id");
    await userEvent.selectOptions(select("Connection"), "Acme Lab · not verified yet");
    expect(site(panel.settings())).toEqual({ type: "string", title: "Site", "x-dewpoint-picker": { ...PICKER, connection: C2 } });
    await userEvent.selectOptions(select("Its choices"), "Acme · Org WLANs");
    expect(site(panel.settings())).toEqual({ type: "string", title: "Site", "x-dewpoint-picker": { node: "acme.org_wlans.get@1", field: "wlan_id", connection: C2 } });
    await userEvent.selectOptions(select("Type"), "Text");
    expect(site(panel.settings())).toEqual({ type: "string", title: "Site" });
  });

  it("holds the list again, the field plain text, once its connection is cleared", async () => {
    const panel = await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    await userEvent.selectOptions(select("Connection"), "Choose a connection");
    expect(site(panel.settings())).toEqual({ type: "string", title: "Site" });
    expect(select("Type").value).toBe("picker");
    expect(select("Its choices").value).toBe("site_id");
  });

  it("reads a picker left unbound at import, its list chosen and its connection to choose", async () => {
    const panel = await showPanel({ doc: draft({ "x-dewpoint-picker": { node: "acme.site_zones.get@1", field: "site_id" } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    expect(select("Its choices").value).toBe("site_id");
    expect(select("Connection").value).toBe("");
    await userEvent.selectOptions(select("Connection"), "Acme Prod · verified");
    expect(site(panel.settings())).toEqual({ type: "string", title: "Site", "x-dewpoint-picker": PICKER });
  });

  it("keeps a half choice through its own edits, and drops it when the draft changes under it, as an undo does", async () => {
    const panel = await showPanel({ doc: draft({}) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    await userEvent.selectOptions(select("Type"), "Choice from a connection");
    await userEvent.selectOptions(select("Its choices"), "Acme · Org sites");
    await userEvent.click(within(field()).getByRole("checkbox", { name: "Required" }));
    expect(select("Type").value).toBe("picker");
    expect(select("Its choices").value).toBe("site_id");
    panel.replace(draft({ title: "Site name" }));
    expect(select("Type").value).toBe("text");
    expect(within(field()).queryByRole("combobox", { name: "Its choices" })).toBeNull();
  });

  it("says when there's no connection of the list's kind, and where to add one", async () => {
    connections = [CONNECTIONS[2]];
    await showPanel({ doc: draft({}) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    await userEvent.selectOptions(select("Type"), "Choice from a connection");
    await userEvent.selectOptions(select("Its choices"), "Acme · Org sites");
    const connection = await within(field()).findByRole<HTMLSelectElement>("combobox", { name: "Connection" });
    await vi.waitFor(() => expect([...connection.options].map((o) => o.text)).toEqual(["No Acme connection"]));
    expect(connection.disabled).toBe(true);
    const says = within(field()).getByText((_, el) => el?.tagName === "P" && el.textContent === "No Acme connection yet: add one on Connections, then choose it here.");
    expect(within(says).getByRole("link", { name: "add one on Connections" }).getAttribute("href")).toBe("/t/t1/connections");
  });

  it("can't be chosen for a sensitive field: its picks would be named on screen", async () => {
    await showPanel({ doc: draft({ "x-sensitive": true }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    expect(within(field()).getByRole<HTMLOptionElement>("option", { name: "Choice from a connection" }).disabled).toBe(true);
  });
});

describe("a Choice from a connection, in its row (the Authoring and Read only boards)", () => {
  it("says the list and the connection it's chosen from, for an editor and a viewer alike", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }), editable: false, viewer: true });
    await vi.waitFor(() => expect(within(input()).getAllByRole("listitem")[0]!.textContent).toBe("site · Site · a choice of Acme Prod's sites · required"));
  });

  it("calls a connection this tenant doesn't hold “the connection”, and a list this server doesn't offer “choices”", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": { node: "acme.gone.get@1", field: "gone_id", connection: "00000000-0000-4000-8000-0000000000ff" } }) });
    await vi.waitFor(() => expect(within(input()).getAllByRole("listitem")[0]!.textContent).toContain("site · Site · a choice of the connection's choices · required"));
  });
});

describe("a Choice from a connection, tried in its editor (the 4f-3 design §5.7)", () => {
  it("tries the list as the form will show it, through the list's step and connection, never closing the field on Escape", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    expect(within(field()).getByRole("status").textContent).toBe("Try the list as the form will show it.");
    const show = within(field()).getByRole("button", { name: "Show choices: Site" });
    await userEvent.click(show);
    const list = await within(field()).findByRole("listbox", { name: "Choices for Site" });
    expect(sent.find((r) => `${r.method} ${r.path}` === OPTIONS)?.body).toEqual({ field: "site_id", connection_id: C1, query: "" });
    await vi.waitFor(() => expect(within(field()).getByRole("status").textContent).toBe("2 of Acme Prod's sites."));
    expect(document.activeElement).toBe(list); // as the step drawer's list does (ruling 338)
    await userEvent.keyboard("{Escape}");
    expect(within(field()).queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(show);
    expect(field()).toBeTruthy(); // the list closed, not the field's editor
  });

  it("offers Show choices only once the list and the connection are both chosen", async () => {
    await showPanel({ doc: draft({}) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    await userEvent.selectOptions(select("Type"), "Choice from a connection");
    await userEvent.selectOptions(select("Its choices"), "Acme · Org sites");
    expect(within(field()).queryByRole("button", { name: /^Show choices/ })).toBeNull();
  });
});

describe("a field's editor below 640 px (the 4f-3 design §5.10; the Narrow320 boards)", () => {
  const tall = (el: Element) => expect(el.className).toContain("max-sm:min-h-[44px]");

  it("makes a picker field's controls and buttons 44 px", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    for (const name of ["Name", "Label", "Description (optional)"]) tall(within(field()).getByRole("textbox", { name }));
    for (const name of ["Type", "Its choices", "Connection"]) tall(select(name));
    tall(within(field()).getByRole("checkbox", { name: "Required" }).closest("label")!);
    for (const name of ["Show choices: Site", "Done", "Remove field"]) tall(within(field()).getByRole("button", { name }));
  });

  it("makes a choice's values, a number's default and Sensitive 44 px too", async () => {
    const choice = { type: "object", properties: { band: { type: "string", enum: ["2.4 GHz"] }, floor: { type: "integer" } } };
    await showPanel({ doc: { graph_format: 1, nodes: [], edges: [], settings: { input_schema: choice } } });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit band" }));
    const band = within(input()).getByRole("group", { name: "The field band" });
    tall(within(band).getByRole("textbox", { name: "Value 1" }));
    for (const name of ["Remove 2.4 GHz", "＋ Value"]) tall(within(band).getByRole("button", { name }));
    tall(within(band).getByRole("checkbox", { name: "Sensitive" }).closest("label")!);
    tall(within(band).getByRole("combobox", { name: "Default" }));
    await userEvent.click(within(band).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit floor" }));
    tall(within(within(input()).getByRole("group", { name: "The field floor" })).getByRole("textbox", { name: "Default" }));
  });
});

describe("a Choice from a connection's problems (the 4f-3 design §5.8; the Authoring board)", () => {
  const at = "/settings/input_schema/properties/site/x-dewpoint-picker";
  const problem = (code: string, message: string): Diagnostic => ({ code, severity: "error", message, fix: null, node: null, field: at });
  const checked = (diagnostics: Diagnostic[]): Validation => ({
    draft_revision: 1, valid: false, diagnostics, expressions: [], taint: { sites: [], declassified: [] }, conditional_steps: [], schedule_breaks: [],
  });  // prettier-ignore
  const describedBy = (el: HTMLElement) => (el.getAttribute("aria-describedby") ?? "").split(" ").map((id) => document.getElementById(id)?.textContent).join(" ");

  it("opens at Connection on Go to a picker's problem, once its list has loaded, the problem under it", async () => {
    let answer: () => void = () => undefined;
    listConnections = () => new Promise<Response>((resolve) => (answer = () => resolve(json(CONNECTIONS))));
    const check = checked([problem("picker.invalid", "A picker needs its connection.")]);
    await showPanel({ doc: draft({ "x-dewpoint-picker": { node: "acme.site_zones.get@1", field: "site_id" } }), check, focusAt: { pointer: at, n: 1 } });
    await within(field()).findByText("Loading connections…");
    await act(() => Promise.resolve(answer()));
    await vi.waitFor(() => expect(document.activeElement).toBe(select("Connection")));
    expect(select("Connection").getAttribute("aria-invalid")).toBe("true");
    expect(describedBy(select("Connection"))).toContain("A picker needs its connection.");
  });

  it("opens at Connection on Go to its connection's own pointer too", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }), focusAt: { pointer: `${at}/connection`, n: 1 } });
    await vi.waitFor(() => expect(document.activeElement).toBe(select("Connection")));
  });

  it("shows what publish found under the field's row and its Connection, never twice (the 4f-3 design §5.8)", async () => {
    const found = [problem("picker.connection_unknown", "No connection of this tenant has that id: a picker lists options through one.")];
    await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }), found });
    expect(within(input()).getAllByRole("listitem")[0]!.textContent).toContain("No connection of this tenant has that id");
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    expect(select("Connection").getAttribute("aria-invalid")).toBe("true");
    expect(within(field()).getAllByText(/No connection of this tenant has that id/)).toHaveLength(1);
  });
});

describe("a Choice from a connection, the final review's cases", () => {
  const at = "/settings/input_schema/properties/site/x-dewpoint-picker";
  const problem = (message: string): Diagnostic => ({ code: "picker.invalid", severity: "error", message, fix: null, node: null, field: at });
  const checked = (diagnostics: Diagnostic[]): Validation => ({
    draft_revision: 1, valid: false, diagnostics, expressions: [], taint: { sites: [], declassified: [] }, conditional_steps: [], schedule_breaks: [],
  });  // prettier-ignore

  it("keeps an unreadable picker's problem under its row on Go to, focus on the row", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": { ...PICKER, extra: 1 } }), check: checked([problem("A picker is a node, a field and a connection.")]), focusAt: { pointer: at, n: 1 } });
    const row = within(input()).getAllByRole("listitem")[0]!;
    expect(row.textContent).toContain("A picker is a node, a field and a connection.");
    await vi.waitFor(() => expect(document.activeElement).toBe(row));
  });

  it("says a picker's problem, and goes to where to add a connection, when the tenant has none of its list's kind", async () => {
    connections = [CONNECTIONS[2]];
    const doc = draft({ "x-dewpoint-picker": { node: "acme.site_zones.get@1", field: "site_id" } });
    await showPanel({ doc, check: checked([problem("A picker needs its connection.")]), focusAt: { pointer: at, n: 1 } });
    await vi.waitFor(() => expect(document.activeElement).toBe(within(field()).getByRole("link", { name: "add one on Connections" })));
    expect(within(field()).getByText("A picker needs its connection.")).toBeTruthy();
  });

  it("names a held connection of a list no step offers any more, and says to choose another list once it's cleared", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": { node: "acme.gone.get@1", field: "gone_id", connection: C1 } }) });
    await vi.waitFor(() => expect(within(input()).getAllByRole("listitem")[0]!.textContent).toContain("a choice of Acme Prod's choices"));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    await vi.waitFor(() => expect(select("Connection").selectedOptions[0]!.text).toBe("Acme Prod · verified"));
    expect(within(field()).queryByText(/isn't in this tenant/)).toBeNull();
    await userEvent.selectOptions(select("Connection"), "Choose a connection");
    expect(within(field()).getByText("This list isn't offered any more: choose another.")).toBeTruthy();
  });

  it("puts Show choices under the field's controls, after Required, as the Authoring board does", async () => {
    await showPanel({ doc: draft({ "x-dewpoint-picker": PICKER }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    const required = within(field()).getByRole("checkbox", { name: "Required" });
    const show = within(field()).getByRole("button", { name: "Show choices: Site" });
    expect(required.compareDocumentPosition(show) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
