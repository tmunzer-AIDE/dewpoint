// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DraftStartForm } from "../../../lib/simulations";
import type { GraphDoc } from "../../../lib/workflows";
import { fakeApi, json } from "../drawer/harness";
import { SimulateDialog } from "./SimulateDialog";

// The OtherForms board's Simulate: the draft's site picked through the node its picker names (a made-up service, D24).
const C1 = "00000000-0000-4000-8000-0000000000c1";
const LYON = "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d";
const picker = (connection: string) => ({ node: "acme.sites.get@1", field: "site_id", connection, list: { plugin: "Acme", title: "Org sites", noun: "sites" } });
const form = (connection: string): DraftStartForm => ({
  workflow_id: "w1", draft_revision: 14, csv: null,
  fields: [{ name: "site_id", title: "Site ID", type: "string", required: true, sensitive: false, picker: picker(connection) }],
});  // prettier-ignore
const SCHEMA = { type: "object", properties: { site_id: { type: "string", "x-dewpoint-picker": picker(C1) } }, required: ["site_id"] };
const doc = { graph_format: 1, nodes: [], edges: [], settings: { input_schema: SCHEMA } } as unknown as GraphDoc;
const OPTIONS = "POST /api/v1/t/t1/node-types/acme.sites.get@1/options";

function show(connection = C1) {
  const sent = fakeApi({
    "GET /api/v1/t/t1/workflows/w1/draft/start-form": () => json(form(connection)),
    "GET /api/v1/trigger-types": () => json([]),
    "GET /api/v1/t/t1/connections": () => json([{ id: C1, name: "Acme Prod", type: "acme", status: "ok", revision: 1, config: {}, secret_set: true }]),
    [OPTIONS]: () => json({ options: [{ value: LYON, label: "Lyon DC" }] }),
  });
  const onSimulate = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SimulateDialog tenantId="t1" workflowId="w1" name="Site onboarding" revision={14} doc={doc} onSimulate={onSimulate} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  return { sent, onSimulate };
}
afterEach(() => vi.restoreAllMocks());

describe("a picker in Simulate (the 4f-3 design §5.3)", () => {
  it("lists through the node the draft's picker names, with its connection, saying it reads the connection now", async () => {
    const { sent, onSimulate } = show();
    await userEvent.type(await screen.findByRole("combobox", { name: /^Site ID/ }), "ly{Enter}");
    await screen.findByRole("listbox", { name: "Choices for Site ID" });
    expect(sent.find((r) => `${r.method} ${r.path}` === OPTIONS)?.body).toEqual({ field: "site_id", connection_id: C1, query: "ly" });
    expect(screen.getByText("Read from Acme Prod now: listing changes nothing in Mist.")).toBeTruthy();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate" }));
    expect(onSimulate).toHaveBeenCalledWith({ site_id: LYON }); // a draft's simulation keeps no names (§4.1)
  });

  it("says a draft whose picker names no connection of this tenant's can't list, asking nothing", async () => {
    const { sent } = show("not-an-id");
    await userEvent.click(await screen.findByRole("button", { name: "Show choices: Site ID" }));
    expect(await screen.findByText("The draft names a connection this tenant doesn't have: choose one in Triggers › Input, or type the site's ID.")).toBeTruthy();
    expect(sent.some((r) => r.path.endsWith("/options"))).toBe(false);
  });
});
