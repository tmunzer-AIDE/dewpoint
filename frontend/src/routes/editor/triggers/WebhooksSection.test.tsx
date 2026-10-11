// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../../lib/workflows";
import type { WorkflowBinding } from "../../../lib/triggers";
import { BINDING, DEVICE_EVENTS, ENDPOINT, MIST } from "../../../test/triggers";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

const FORM_FIELDS = { type: "object", properties: { site: { type: "string" }, note: { type: "string" } } };
const OTHER: WorkflowBinding = {
  id: "b2", endpoint_id: "e2", workflow_id: "w1", enabled: true,
  filter: [{ pointer: "/type", value: "incident" }, { pointer: "/priority", value: 1 }],
  endpoint: { id: "e2", name: "Ticketing", enabled: true, auth: "hmac", path: "/hooks/e2", trigger: null },
};  // prettier-ignore
const draft = (input_schema: Record<string, unknown>): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings: { input_schema } });
const section = () => screen.getByRole("region", { name: "Webhooks" });

function api(bindings: WorkflowBinding[], more: Record<string, () => Response | Promise<Response>> = {}) {
  return fakeApi({
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules: [] }),
    "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ workflow_id: "w1", version_id: "v3", fields: [], csv: null }),
    "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: draft(FORM_FIELDS) }),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings }),
    "GET /api/v1/t/t1/webhook-endpoints": () =>
      json({ endpoints: [ENDPOINT, { ...ENDPOINT, id: "e2", name: "Ticketing", trigger: null, auth: "hmac" }, { ...ENDPOINT, id: "e3", name: "Mist lab" }] }),
    ...more,
  });
}
afterEach(() => vi.restoreAllMocks());

describe("a workflow's webhooks", () => {
  it("says each one's sender and when it runs, and what the published input makes of its events", async () => {
    api([BINDING, OTHER]);
    await showPanel({ doc: draft(FORM_FIELDS) });
    const rows = (await within(section()).findAllByRole("listitem")).map((r) => r.textContent ?? "");
    expect(rows[0]).toContain("Mist · topic device-events");
    await vi.waitFor(() => expect(section().textContent).toContain("Version 3's input isn't device-events' shape (it has 2 form fields): events it doesn't fit are refused."));
    expect(rows[1]).toContain("Another sender · /type is incident and /priority is 1");
    expect(rows[1]).toContain("Its events have no known shape: the input must fit them, or each is refused.");
  });

  it("gives the draft the topic's shape, then says it applies once published", async () => {
    api([BINDING]);
    const panel = await showPanel({ doc: draft(FORM_FIELDS) });
    await userEvent.click(await within(section()).findByRole("button", { name: "Use device-events' shape for the input" }));
    expect(panel.settings()?.input_schema).toEqual(DEVICE_EVENTS);
    expect(section().textContent).toContain("In the draft: it applies once published.");
  });

  it("says a binding's events are refused before a first publish", async () => {
    api([BINDING]);
    await showPanel({ doc: draft(FORM_FIELDS), activeNumber: null, activeVersionId: null });
    await vi.waitFor(() => expect(section().textContent).toContain("Events are refused until a version is published, and listed as refused in the endpoint's events."));
  });

  it("adds a Mist webhook for a topic, giving the input its shape in the draft", async () => {
    const sent = api([OTHER], { "POST /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ ...BINDING, endpoint: undefined }, 201) });
    const panel = await showPanel({ doc: draft(FORM_FIELDS) });
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    expect(form.querySelector("dialog")).toBeNull(); // nothing to remove yet: no question waits in it, closed or not
    const endpoint = within(form).getByRole("combobox", { name: "Endpoint" });
    await vi.waitFor(() => expect(within(endpoint).getByRole<HTMLOptionElement>("option", { name: "Ticketing · already starts this workflow" }).disabled).toBe(true));
    await userEvent.selectOptions(endpoint, "e1");
    expect(form.textContent).toContain("Mist sends every topic you subscribe to one URL; this workflow runs for this one.");
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Topic" }), "device-events");
    expect(form.textContent).toContain("Replaces the input's 2 fields, in the draft: Undo brings them back.");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({ workflow_id: "w1", filter: [{ pointer: "/topic", value: "device-events" }] }),
    );
    await vi.waitFor(() => expect(panel.settings()?.input_schema).toEqual(DEVICE_EVENTS));
  });

  it("adds another sender's webhook with typed conditions, checked before anything is sent", async () => {
    const sent = api([], { "POST /api/v1/t/t1/webhook-endpoints/e2/bindings": () => json({ ...OTHER, endpoint: undefined }, 201) });
    await showPanel();
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    await vi.waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e2");
    await userEvent.click(within(form).getByRole("button", { name: "＋ Condition" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Field 1" }), "type");
    await userEvent.type(within(form).getByRole("textbox", { name: "Value 1" }), "incident");
    await userEvent.click(within(form).getByRole("button", { name: "＋ Condition" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Field 2" }), "/priority");
    await userEvent.type(within(form).getByRole("textbox", { name: "Value 2" }), "1");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    expect(form.textContent).toContain("A field is a pointer into the event, starting with /, like /type.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.type(within(form).getByRole("textbox", { name: "Field 1" }), "{Home}/");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({ workflow_id: "w1", filter: [{ pointer: "/type", value: "incident" }, { pointer: "/priority", value: 1 }] }),
    );
  });

  it("says the API's refusal in words", async () => {
    api([], { "POST /api/v1/t/t1/webhook-endpoints/e3/bindings": () => json({ error: "binding_cap" }, 409) });
    await showPanel();
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    await vi.waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e3");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    expect(await within(form).findByRole("alert")).toHaveProperty("textContent", "This endpoint starts 20 workflows, its most: remove one there first.");
  });

  it("keeps every condition of a filter a topic can't say, and saves it unchanged as it was", async () => {
    // The review of revision 1: a topic and a site, saved unchanged, lost the site, and the first topic won.
    const both: WorkflowBinding = { ...BINDING, filter: [{ pointer: "/topic", value: "device-events" }, { pointer: "/site", value: " HQ " }] };
    const sent = api([both], { "PATCH /api/v1/t/t1/webhook-bindings/b1": () => json(both) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Mist prod" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Mist prod" });
    expect(within(form).queryByRole("combobox", { name: "Topic" })).toBeNull();
    expect(form.textContent).toContain("Its conditions aren't a topic alone: they're kept as they are, and change here.");
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Value 2" }).value).toBe('" HQ "');
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ filter: both.filter }));
  });

  it("waits for what an endpoint sends before showing its topic, so a save never changes it", async () => {
    // The review of revision 1: the trigger types answering after the form opened gave it the first topic.
    let types: ((r: Response) => void) | undefined;
    const sent = api([BINDING], {
      "GET /api/v1/trigger-types": () => new Promise<Response>((resolve) => (types = resolve)),
      "PATCH /api/v1/t/t1/webhook-bindings/b1": () => json(BINDING),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Mist prod" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Mist prod" });
    expect(within(form).getByRole<HTMLButtonElement>("button", { name: "Save" }).disabled).toBe(true);
    await vi.waitFor(() => expect(types).toBeDefined());
    types!(json([MIST]));
    const topic = await within(form).findByRole<HTMLSelectElement>("combobox", { name: "Topic" });
    expect(topic.value).toBe("device-events");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ filter: BINDING.filter }));
  });

  it("says when what an endpoint sends can't be loaded, and adds nothing for it until it is", async () => {
    // The review of revision 2: trigger types failing left a Mist endpoint without a topic: Add bound it to every event.
    let failing = true;
    const sent = api([], {
      "GET /api/v1/trigger-types": () => (failing ? json({ error: "unavailable" }, 503) : json([MIST])),
      "POST /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ ...BINDING, endpoint: undefined }, 201),
    });
    await showPanel();
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    await vi.waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e1");
    expect(await within(form).findByText("What this endpoint sends couldn't be loaded, so its topics can't be shown.")).toBeTruthy();
    expect(within(form).getByRole<HTMLButtonElement>("button", { name: "Add the webhook" }).disabled).toBe(true);
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e2"); // another sender's needs none
    expect(within(form).getByRole("button", { name: "＋ Condition" })).toBeTruthy();
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e1");
    failing = false;
    await userEvent.click(within(form).getByRole("button", { name: "Try again" }));
    await userEvent.selectOptions(await within(form).findByRole("combobox", { name: "Topic" }), "alarms");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "POST")?.body).toEqual({ workflow_id: "w1", filter: [{ pointer: "/topic", value: "alarms" }] }));
  });

  it("names a binding's sender by its key while the senders there are can't be read, never as unknown", async () => {
    // The final review: a pending or failed /trigger-types read as "An unknown sender (mist.webhook)".
    api([BINDING], { "GET /api/v1/trigger-types": () => json({ error: "unavailable" }, 503) });
    await showPanel();
    await within(section()).findByRole("button", { name: "Edit Mist prod" });
    expect(section().textContent).not.toContain("An unknown sender");
    expect(section().textContent).toContain("mist.webhook · /topic is device-events");
  });

  it("keeps a value with a line break as it was when a sibling condition is saved", async () => {
    // The final review: a one-line field drops a line break, so "a\nb" (made through the API) was sent as "ab".
    const broken: WorkflowBinding = { ...OTHER, filter: [{ pointer: "/type", value: "a\nb" }, { pointer: "/priority", value: 1 }] };
    const sent = api([broken], { "PATCH /api/v1/t/t1/webhook-bindings/b2": () => json(broken) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Ticketing" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Ticketing" });
    // Shown as JSON text, which a one-line field keeps (jsdom keeps a raw break; a browser drops it).
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Value 1" }).value).toBe('"a\\nb"');
    await userEvent.clear(within(form).getByRole("textbox", { name: "Value 2" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Value 2" }), "2");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ filter: [{ pointer: "/type", value: "a\nb" }, { pointer: "/priority", value: 2 }] }));
  });

  it("keeps a field with a line break as it was when a sibling condition is saved", async () => {
    // The review of the final head: "/room\nname" showed as "/roomname", and an edit to it saved that.
    const broken: WorkflowBinding = { ...OTHER, filter: [{ pointer: "/room\nname", value: "a" }, { pointer: "/priority", value: 1 }] };
    const sent = api([broken], { "PATCH /api/v1/t/t1/webhook-bindings/b2": () => json(broken) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Ticketing" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Ticketing" });
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Field 1" }).value).toBe(JSON.stringify("/room\nname"));
    await userEvent.clear(within(form).getByRole("textbox", { name: "Value 2" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Value 2" }), "2");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ filter: [{ pointer: "/room\nname", value: "a" }, { pointer: "/priority", value: 2 }] }));
  });

  it("says a condition's refusal to whoever reads its field and its value", async () => {
    // The final review: the refusal showed under the condition, but neither control was described by it.
    api([OTHER]);
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Ticketing" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Ticketing" });
    await userEvent.clear(within(form).getByRole("textbox", { name: "Field 1" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Field 1" }), "type");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    const why = "A field is a pointer into the event, starting with /, like /type.";
    expect(within(form).getByRole("textbox", { name: "Field 1", description: why })).toBeTruthy();
    expect(within(form).getByRole("textbox", { name: "Value 1", description: why })).toBeTruthy();
  });

  it("changes one's conditions, turns one off at once, and removes one after asking", async () => {
    const sent = api([OTHER], {
      "PATCH /api/v1/t/t1/webhook-bindings/b2": () => json(OTHER),
      "DELETE /api/v1/t/t1/webhook-bindings/b2": () => new Response(null, { status: 204 }),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("switch", { name: "Ticketing" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ enabled: false }));
    await userEvent.click(within(section()).getByRole("button", { name: "Edit Ticketing" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Ticketing" });
    await userEvent.click(within(form).getByRole("button", { name: "Remove condition 2" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.filter((r) => r.method === "PATCH").at(-1)?.body).toEqual({ filter: [{ pointer: "/type", value: "incident" }] }));
    await userEvent.click(within(section()).getByRole("button", { name: "Edit Ticketing" }));
    await userEvent.click(within(section()).getByRole("button", { name: "Remove the webhook…" }));
    const ask = screen.getByRole("dialog", { name: "Remove the webhook from Ticketing?" });
    await userEvent.click(within(ask).getByRole("button", { name: "Remove the webhook" }));
    await vi.waitFor(() => expect(sent.some((r) => r.method === "DELETE")).toBe(true));
  });
});
