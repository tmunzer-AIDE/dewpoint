// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { REMOTE, RUN_WORKFLOW, typeWith } from "../../../test/nodeTypes";
import { fakeApi, json, showFields } from "./harness";

afterEach(() => {
  vi.restoreAllMocks();
});

const C1 = "00000000-0000-4000-8000-0000000000c1";
const C2 = "00000000-0000-4000-8000-0000000000c2";
const CONNECTIONS = "GET /api/v1/t/t1/connections";
const TYPES = "GET /api/v1/connection-types";
const acmeType = { key: "acme", label: "Acme Cloud", config_schema: {}, secret_fields: [], clouds: null };
const connection = (id: string, name: string, type: string, status: "ok" | "unverified" | "error") => ({
  id, name, type, status, revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
});  // prettier-ignore

it("lists the tenant's connections of the field's type, with their status in words", async () => {
  fakeApi({
    [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok"), connection(C2, "Lab", "acme", "unverified"), connection("c3", "Chat", "slack", "ok")]),
  });
  const { config } = showFields(REMOTE);
  const select = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Connection" });
  expect([...select.options].map((o) => o.textContent)).toEqual(["Choose a connection", "Prod · verified", "Lab · not verified yet"]);
  await userEvent.selectOptions(select, "Lab · not verified yet");
  expect(config().connection).toBe(C2);
});

it("links to Connections when there's no Mist connection yet", async () => {
  fakeApi({ [CONNECTIONS]: () => json([]) });
  const mist = typeWith({
    type: "object", required: ["connection"],
    properties: { connection: { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": "mist" } },
  });  // prettier-ignore
  showFields(mist, { routed: true });
  const link = await screen.findByRole("link", { name: "Add one in Connections" });
  expect(link.getAttribute("href")).toBe("/t/t1/connections");
});

it("says an admin adds a connection of any other type, the type named by its label (4f-1)", async () => {
  fakeApi({ [CONNECTIONS]: () => json([]), [TYPES]: () => json([acmeType]) });
  showFields(REMOTE);
  expect(await screen.findByText("No Acme Cloud connection yet: an admin adds one.")).toBeTruthy();
});

it("never names a connection's type by its key, even when its label can't be read", async () => {
  fakeApi({ [CONNECTIONS]: () => json([]), [TYPES]: () => json({ error: "internal" }, 500) });
  showFields(REMOTE);
  expect(await screen.findByText("No connection of its type yet: an admin adds one.")).toBeTruthy();
});

it("shows a connection that isn't in this tenant until it's changed", async () => {
  fakeApi({ [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok")]) });
  showFields(REMOTE, { config: { connection: "00000000-0000-4000-8000-0000000000ff" } });
  const select = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Connection" });
  expect(select.selectedOptions[0]!.textContent).toBe("A connection that isn't in this tenant");
});

it("lists this tenant's other workflows", async () => {
  fakeApi({ "GET /api/v1/t/t1/workflows": () => json([{ id: "w1", name: "This one" }, { id: "w2", name: "Nightly" }]) });
  const { config } = showFields(RUN_WORKFLOW);
  const select = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Workflow" });
  expect([...select.options].map((o) => o.textContent)).toEqual(["Choose a workflow", "Nightly"]);
  await userEvent.selectOptions(select, "Nightly");
  expect(config().workflow_id).toBe("w2");
});

// Every state names a control for the field's label (#73): the label's `for` never points at nothing.

it("names the connection field's control while its list loads", async () => {
  fakeApi({ [CONNECTIONS]: () => new Promise<Response>(() => undefined) });
  showFields(REMOTE);
  expect((await screen.findByLabelText("Connection")).textContent).toBe("Loading connections…");
});

it("names the connection field's control after its list failed, its Try again inside", async () => {
  fakeApi({ [CONNECTIONS]: () => json({ error: "internal" }, 500) });
  showFields(REMOTE);
  await screen.findByText("Connections couldn't load.", { exact: false });
  expect(within(screen.getByLabelText("Connection")).getByRole("button", { name: "Try again" })).toBeTruthy();
});

it("names the connection field's control with nothing to choose", async () => {
  fakeApi({ [CONNECTIONS]: () => json([]), [TYPES]: () => json([acmeType]) });
  showFields(REMOTE);
  await screen.findByText("No Acme Cloud connection yet: an admin adds one.");
  expect(screen.getByLabelText("Connection").textContent).toBe("No Acme Cloud connection yet: an admin adds one.");
});

it("names the workflow field's control while its list loads and with nothing to choose", async () => {
  let answer: (r: Response) => void = () => undefined;
  fakeApi({ "GET /api/v1/t/t1/workflows": () => new Promise<Response>((resolve) => (answer = resolve)) });
  showFields(RUN_WORKFLOW);
  expect((await screen.findByLabelText("Workflow")).textContent).toBe("Loading workflows…");
  answer(json([{ id: "w1", name: "This one" }]));
  await screen.findByText("No other workflow yet.");
  expect(screen.getByLabelText("Workflow").textContent).toBe("No other workflow yet.");
});

/** A connection field marked by its widget only: it doesn't say which kind of connection it takes. */
const UNMARKED = typeWith({ type: "object", properties: { connection: { type: "string", title: "Connection", "x-widget": "connection" } } });

it("says a connection field without its kind takes none, never a blank kind", async () => {
  fakeApi({ [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok")]) });
  showFields(UNMARKED);
  await screen.findByText("This field doesn't say which kind of connection it takes.");
  expect(screen.getByLabelText("Connection").textContent).toBe("This field doesn't say which kind of connection it takes.");
  expect(document.body.textContent).not.toContain("No  connection");
});

it("keeps a connection field's value, and its clearing, when the field doesn't say its kind (the review)", async () => {
  fakeApi({ [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok")]) });
  const { config } = showFields(UNMARKED, { config: { connection: C1 } });
  const select = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Connection" });
  expect(select.selectedOptions[0]!.textContent).toBe("A connection that isn't in this tenant");
  await userEvent.selectOptions(select, "Choose a connection");
  expect(config()).not.toHaveProperty("connection");
});
