// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../../lib/workflows";
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

let connections: unknown[];
beforeEach(() => {
  connections = CONNECTIONS;
  fakeApi({
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/node-types": () => json(LISTING),
    "GET /api/v1/t/t1/connections": () => json(connections),
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
