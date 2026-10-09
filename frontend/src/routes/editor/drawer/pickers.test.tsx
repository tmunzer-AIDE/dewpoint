// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
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
const connection = (id: string, name: string, type: string, status: "ok" | "unverified" | "error") => ({
  id, name, type, status, revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
});  // prettier-ignore

it("lists the tenant's connections of the field's type, with their status in words", async () => {
  fakeApi({
    [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok"), connection(C2, "Lab", "acme", "unverified"), connection("c3", "Chat", "slack", "ok")]),
  });
  const { config } = showFields(REMOTE);
  const select = await screen.findByLabelText<HTMLSelectElement>("Connection");
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

it("says an admin adds a connection of any other type", async () => {
  fakeApi({ [CONNECTIONS]: () => json([]) });
  showFields(REMOTE);
  expect(await screen.findByText("No acme connection yet: an admin adds one.")).toBeTruthy();
});

it("shows a connection that isn't in this tenant until it's changed", async () => {
  fakeApi({ [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok")]) });
  showFields(REMOTE, { config: { connection: "00000000-0000-4000-8000-0000000000ff" } });
  const select = await screen.findByLabelText<HTMLSelectElement>("Connection");
  expect(select.selectedOptions[0]!.textContent).toBe("A connection that isn't in this tenant");
});

it("lists this tenant's other workflows", async () => {
  fakeApi({ "GET /api/v1/t/t1/workflows": () => json([{ id: "w1", name: "This one" }, { id: "w2", name: "Nightly" }]) });
  const { config } = showFields(RUN_WORKFLOW);
  const select = await screen.findByLabelText<HTMLSelectElement>("Workflow Id");
  expect([...select.options].map((o) => o.textContent)).toEqual(["Choose a workflow", "Nightly"]);
  await userEvent.selectOptions(select, "Nightly");
  expect(config().workflow_id).toBe("w2");
});
