// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DraftStartForm } from "../../../lib/simulations";
import type { GraphDoc } from "../../../lib/workflows";
import { SimulateDialog } from "./SimulateDialog";

const SCHEMA = {
  type: "object",
  properties: { site: { type: "string" }, floor: { type: "integer" }, api_token: { type: "string", "x-sensitive": true } },
  required: ["site", "api_token"],
};
const FORM: DraftStartForm = {
  workflow_id: "w1",
  draft_revision: 14,
  csv: null,
  fields: [
    { name: "site", title: "Site", type: "string", required: true, sensitive: false, description: "The site's name, as in Mist." },
    { name: "floor", title: "Floor", type: "integer", required: false, sensitive: false },
    { name: "api_token", title: "API token", type: "string", required: true, sensitive: true },
  ],
};
const EVENT = {
  type: "object",
  properties: { topic: { type: "string" }, events: { type: "array", items: { type: "object", properties: { mac: { type: "string" }, timestamp: { type: "integer" } } } } },
};  // prettier-ignore
const doc = (input_schema: unknown): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings: { input_schema } }) as unknown as GraphDoc;

let form: DraftStartForm;
let types: unknown[];
let asked: string[];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  form = FORM;
  types = [];
  asked = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = new URL((input as Request).url);
    asked.push(url.pathname + url.search);
    if (url.pathname === "/api/v1/t/t1/workflows/w1/draft/start-form") return Promise.resolve(json(form));
    if (url.pathname === "/api/v1/trigger-types") return Promise.resolve(json(types));
    return Promise.resolve(json({ error: "not_found" }, 404));
  });
});
afterEach(() => vi.restoreAllMocks());

/** What a control's description says: its hint and its error, as a screen reader reads them. */
const description = (el: HTMLElement) =>
  (el.getAttribute("aria-describedby") ?? "").split(" ").filter(Boolean).map((id) => document.getElementById(id)?.textContent ?? "").join(" ");

function show(input: unknown = SCHEMA) {
  const onSimulate = vi.fn();
  const onClose = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SimulateDialog tenantId="t1" workflowId="w1" name="AP offline alert" revision={14} doc={doc(input)} onSimulate={onSimulate} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onSimulate, onClose };
}

describe("Simulate workflow's input (§7.1; the InputFields, InputJson boards)", () => {
  it("is the draft's own form at the revision being simulated, sensitive values typed, never shown", async () => {
    const { onSimulate } = show();
    expect(await screen.findByRole("heading", { name: "Simulate workflow" })).toBeTruthy();
    expect(screen.getByText("AP offline alert · draft revision 14")).toBeTruthy();
    expect(asked).toContain("/api/v1/t/t1/workflows/w1/draft/start-form?revision=14");
    expect(description(await screen.findByLabelText("Site required"))).toBe("The site's name, as in Mist.");
    expect(description(screen.getByLabelText("Floor"))).toBe("Optional: left out when empty.");
    const token = screen.getByLabelText("API token required sensitive");
    expect(token.getAttribute("type")).toBe("password");
    expect(description(token)).toBe("Stored as a protected value: results show it as redacted.");
    await userEvent.type(screen.getByLabelText("Site required"), "HQ Paris");
    await userEvent.type(token, "t0ken");
    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate" }));
    expect(onSimulate).toHaveBeenCalledWith({ site: "HQ Paris", api_token: "t0ken" }); // an empty optional field is left out
  });

  it("asks for a required value before anything is sent", async () => {
    const { onSimulate } = show();
    await userEvent.click(await screen.findByRole("button", { name: "◌ Simulate" }));
    expect(description(await screen.findByLabelText("Site required"))).toContain("Give a value: the input requires it.");
    expect(onSimulate).not.toHaveBeenCalled();
  });

  it("can be edited as JSON, what's typed going with it", async () => {
    const { onSimulate } = show();
    await userEvent.type(await screen.findByLabelText("Site required"), "HQ");
    await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
    const area = screen.getByLabelText("The input, as JSON");
    expect(JSON.parse((area as HTMLTextAreaElement).value)).toEqual({ site: "HQ" });
    await userEvent.clear(area);
    await userEvent.type(area, '{{"site": "HQ", "floor": 2, "api_token": "x"}');
    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate" }));
    expect(onSimulate).toHaveBeenCalledWith({ site: "HQ", floor: 2, api_token: "x" });
  });

  it("starts a Mist event's input from a skeleton of its shape, labelled as such", async () => {
    types = [{ key: "mist", label: "Mist", plugin: "mist", topic_pointer: "/topic", endpoint: {}, topics: { "device-events": EVENT } }];
    form = { ...FORM, fields: [] };
    const { onSimulate } = show(EVENT);
    const area = await screen.findByLabelText("Input, as a device-events event");
    expect(JSON.parse((area as HTMLTextAreaElement).value)).toEqual({ topic: "", events: [{ mac: "", timestamp: 0 }] });
    expect(description(area)).toBe("A generated skeleton: every field the input declares, filled with empty values of its type. Fill it with the event you want to try.");
    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate" }));
    expect(onSimulate).toHaveBeenCalledWith({ topic: "", events: [{ mac: "", timestamp: 0 }] });
  });

  it("says a CSV input can't be simulated whole yet, and that Simulate step still works", async () => {
    form = { ...FORM, csv: { max_rows: 10, max_bytes: 1000, columns: [] } };
    const { onClose } = show();
    expect(await screen.findByText(/This draft's input takes a CSV file, and a simulation can't take one yet\./)).toBeTruthy();
    expect(screen.getByText(/Simulate step still works: a step's values, rows included, are typed in its Test tab\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "◌ Simulate" })).toHaveProperty("disabled", true);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("is cancelled without sending anything", async () => {
    const { onSimulate, onClose } = show();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(onSimulate).not.toHaveBeenCalled();
  });
});
