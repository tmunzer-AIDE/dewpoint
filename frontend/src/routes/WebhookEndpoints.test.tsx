// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Endpoint, EndpointBinding } from "../lib/triggers";
import { ENDPOINT, MIST } from "../test/triggers";
import { fakeApi, json } from "./editor/drawer/harness";
import { WebhookEndpointsPage } from "./WebhookEndpoints";

const TICKETING: Endpoint = {
  ...ENDPOINT, id: "e2", name: "Ticketing", auth: "hmac", trigger: null, signature_header: "x-dewpoint-signature",
  timestamp_header: "x-dewpoint-timestamp", events_pointer: "/items", id_source: "pointer", id_pointer: "/id", pending_events: 2, path: "/hooks/e2",
};  // prettier-ignore
const LAB: Endpoint = { ...ENDPOINT, id: "e3", name: "Mist lab", enabled: false, path: "/hooks/e3" };
const bound = (id: string, workflow: string, topic: string | null): EndpointBinding => ({
  id, endpoint_id: "e1", workflow_id: workflow, enabled: true, filter: topic ? [{ pointer: "/topic", value: topic }] : [],
});  // prettier-ignore

function api(role: string, environment: string | null = "production", more: Record<string, () => Response | Promise<Response>> = {}) {
  return fakeApi({
    "GET /api/v1/t/t1": () => json({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }),
    "GET /api/v1/platform/status": () => json({ environment, production_runs: false }),
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/t/t1/workflows": () => json([{ id: "w1", name: "AP report" }, { id: "w2", name: "Site audit" }]),
    "GET /api/v1/t/t1/webhook-endpoints": () => json({ endpoints: [ENDPOINT, TICKETING, LAB] }),
    "GET /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ bindings: [bound("b1", "w1", "device-events"), bound("b2", "w2", "alarms")] }),
    "GET /api/v1/t/t1/webhook-endpoints/e2/bindings": () => json({ bindings: [] }),
    "GET /api/v1/t/t1/webhook-endpoints/e3/bindings": () => json({ bindings: [] }),
    ...more,
  });
}

async function show() {
  const root = createRootRoute();
  const page = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => (
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <WebhookEndpointsPage tenantId="t1" />
      </QueryClientProvider>
    ),
  });
  render(<RouterProvider router={createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ["/"] }) })} />);
  await screen.findByRole("heading", { name: "Webhook endpoints" });
}
const table = () => screen.getByRole("region", { name: "Webhook endpoints" });
afterEach(() => vi.restoreAllMocks());

describe("Settings → Webhook endpoints", () => {
  it("lists each endpoint's sender, proof, workflows, waiting events, state and path, as the Endpoints board does", async () => {
    api("editor");
    await show();
    await vi.waitFor(() => expect(within(table()).getAllByRole("row")[1]!.textContent).toBe("Mist prodMistA token20/hooks/e1Details"));
    const rows = within(table()).getAllByRole("row").map((r) => r.textContent);
    expect(rows[2]).toBe("TicketingAnother senderAn HMAC signature02/hooks/e2Details");
    expect(within(table()).getByRole("switch", { name: "Mist lab" }).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(/An endpoint is turned off rather than deleted/)).toBeTruthy();
  });

  it("says a deployment receives no webhooks yet outside development, and nothing in development", async () => {
    api("editor", "production");
    await show();
    expect(await screen.findByText("This deployment doesn't receive webhooks yet: only development deployments do, for now.")).toBeTruthy();
  });

  it("says nothing of it in a development deployment", async () => {
    api("editor", "development");
    await show();
    await within(table()).findByText("Mist prod");
    expect(screen.queryByText(/doesn't receive webhooks yet/)).toBeNull();
  });

  it("shows an endpoint's details: the workflows it starts, with their topics, and its path", async () => {
    api("editor");
    await show();
    await userEvent.click(await within(table()).findByRole("button", { name: "Mist prod, details" }));
    const details = within(table()).getAllByRole("row")[2]!;
    expect(details.textContent).toContain("Path /hooks/e1, on your Dewpoint webhook address.");
    expect(within(details).getByRole("link", { name: "AP report · device-events" })).toBeTruthy();
    expect(within(details).getByRole("link", { name: "Site audit · alarms" })).toBeTruthy();
  });

  it("makes a Mist endpoint from its name alone, and shows its token once", async () => {
    const sent = api("editor", "development", { "POST /api/v1/t/t1/webhook-endpoints": () => json({ ...ENDPOINT, id: "e9", secret: "tok-123" }, 201) });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" })); // once the role is known
    const form = screen.getByRole("form", { name: "New endpoint" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Mist prod");
    expect(within(form).getByRole<HTMLInputElement>("radio", { name: "Mist" }).checked).toBe(true);
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({ name: "Mist prod", allowlist: [], body_limit: 1_048_576, trigger: "mist.webhook" }),
    );
    const shown = await screen.findByRole("status");
    expect(shown.textContent).toContain("Mist prod is ready");
    expect(shown.textContent).toContain("tok-123");
    await userEvent.click(within(shown).getByRole("button", { name: "I've copied it" }));
    expect(screen.queryByText("tok-123")).toBeNull();
  });

  it("makes another sender's endpoint, its proof, events and ids fixed, and says a refused field at its field", async () => {
    const sent = api("editor", "development", {
      "POST /api/v1/t/t1/webhook-endpoints": () => json({ error: "endpoint_invalid", fields: ["id_pointer"] }, 422),
    });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" })); // once the role is known
    const form = screen.getByRole("form", { name: "New endpoint" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Ticketing");
    await userEvent.click(within(form).getByRole("radio", { name: "Another sender" }));
    await userEvent.click(within(form).getByRole("radio", { name: "An HMAC signature" }));
    await userEvent.click(within(form).getByRole("radio", { name: /^A list in the body, at/ }));
    await userEvent.click(within(form).getByRole("radio", { name: /^In each event, at/ }));
    const id = within(form).getByRole("textbox", { name: "The id's pointer" });
    await userEvent.clear(id);
    await userEvent.type(id, "id");
    expect(form.textContent).toContain("Fixed once made: an HMAC signature; events in the list at /items; each event's id: its pointer needs fixing first.");
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    await vi.waitFor(() => expect(form.textContent).toContain("A pointer starts with /, like /id, at most 256 characters."));
    expect(sent.find((r) => r.method === "POST")?.body).toMatchObject({ auth: "hmac", events_pointer: "/items", id_source: "pointer", id_pointer: "id" });
  });

  it("rotates a token after asking, and shows the new one once", async () => {
    const sent = api("editor", "development", { "POST /api/v1/t/t1/webhook-endpoints/e1/secret": () => json({ id: "e1", secret: "tok-new" }) });
    await show();
    await userEvent.click(await within(table()).findByRole("button", { name: "Mist prod, details" }));
    await userEvent.click(within(table()).getByRole("button", { name: "Rotate the token…" }));
    const ask = screen.getByRole("dialog", { name: "Rotate Mist prod's token?" });
    expect(ask.textContent).toContain("The old token stops working now: Mist's events are refused until it sends the new one.");
    await userEvent.click(within(ask).getByRole("button", { name: "Rotate the token" }));
    expect((await screen.findByRole("status")).textContent).toContain("tok-new");
    expect(sent.some((r) => r.method === "POST" && r.path.endsWith("/secret"))).toBe(true);
  });

  it("edits what may change, beside what was fixed when it was made", async () => {
    const sent = api("editor", "development", { "PATCH /api/v1/t/t1/webhook-endpoints/e2": () => json({ ...TICKETING, name: "Tickets" }) });
    await show();
    await userEvent.click(await within(table()).findByRole("button", { name: "Ticketing, details" }));
    await userEvent.click(within(table()).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Editing Ticketing" });
    expect(form.textContent).toContain("ProofAn HMAC signature");
    expect(form.textContent).toContain("EventsThe list at /items");
    expect(form.textContent).toContain("IdsAt /id in each event");
    const name = within(form).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Tickets");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ name: "Tickets" }));
  });

  it("gives focus to a made endpoint's token, and back to an edited one's details once its form closes", async () => {
    // The final review: creating one, or saving or cancelling an edit, left focus on the page's body.
    api("editor", "development", {
      "POST /api/v1/t/t1/webhook-endpoints": () => json({ ...ENDPOINT, id: "e9", name: "Mist lab 2", secret: "tok-9" }, 201),
      "PATCH /api/v1/t/t1/webhook-endpoints/e2": () => json(TICKETING),
    });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" }));
    await userEvent.type(within(screen.getByRole("form", { name: "New endpoint" })).getByRole("textbox", { name: "Name" }), "Mist lab 2");
    await userEvent.click(screen.getByRole("button", { name: "Create the endpoint" }));
    const shown = await screen.findByRole("status");
    await vi.waitFor(() => expect(document.activeElement).toBe(within(shown).getByRole("heading", { name: "Mist lab 2 is ready" })));
    await userEvent.click(within(shown).getByRole("button", { name: "I've copied it" }));
    const details = () => within(table()).getByRole("button", { name: "Ticketing, details" });
    await userEvent.click(details());
    await userEvent.click(within(table()).getByRole("button", { name: "Edit" }));
    await userEvent.click(within(screen.getByRole("form", { name: "Editing Ticketing" })).getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(details()));
    await userEvent.click(within(table()).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Editing Ticketing" });
    await userEvent.clear(within(form).getByRole("textbox", { name: "Name" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Tickets");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(details()));
  });

  it("names an endpoint's sender by its key while the senders there are can't be read, never as unknown", async () => {
    // The final review: a pending or failed /trigger-types read as "An unknown sender (mist.webhook)".
    api("editor", "development", { "GET /api/v1/trigger-types": () => json({ error: "unavailable" }, 503) });
    await show();
    await within(table()).findByRole("button", { name: "Mist prod, details" });
    expect(table().textContent).not.toContain("An unknown sender");
    expect(table().textContent).toContain("mist.webhook");
  });

  it("says a refused allowlist to whoever reads the allowlist", async () => {
    // The final review: the refusal showed, but the control wasn't described by it.
    api("editor", "development", { "POST /api/v1/t/t1/webhook-endpoints": () => json({ error: "endpoint_invalid", fields: ["allowlist"] }, 422) });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" }));
    const form = screen.getByRole("form", { name: "New endpoint" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Mist lab");
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    expect(await within(form).findByRole("textbox", { name: "Allowed networks", description: /One network a line, like 203\.0\.113\.0\/24/ })).toBeTruthy();
  });

  it("opens the optional settings a refusal is about, and gives the refused control focus", async () => {
    // The review of the final head: refused while folded away, the allowlist's error stayed hidden; nothing showed.
    api("editor", "development", { "POST /api/v1/t/t1/webhook-endpoints": () => json({ error: "endpoint_invalid", fields: ["allowlist"] }, 422) });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" }));
    const form = screen.getByRole("form", { name: "New endpoint" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Mist lab");
    const folded = within(form).getByText("Allowed addresses and the largest event").closest("details")!;
    await userEvent.click(within(form).getByText("Allowed addresses and the largest event"));
    await userEvent.type(within(form).getByRole("textbox", { name: "Allowed networks" }), "10.0.0.1/8");
    await userEvent.click(within(form).getByText("Allowed addresses and the largest event"));
    expect(folded.open).toBe(false);
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    await vi.waitFor(() => expect(folded.open).toBe(true));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(form).getByRole("textbox", { name: "Allowed networks" })));
  });

  it("says each refused pointer and header to whoever reads it", async () => {
    // The review of the final head: the list's pointer, the id's pointer and header were marked invalid without why.
    let fields = ["events_pointer", "id_pointer"];
    api("editor", "development", { "POST /api/v1/t/t1/webhook-endpoints": () => json({ error: "endpoint_invalid", fields }, 422) });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" }));
    const form = screen.getByRole("form", { name: "New endpoint" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Ticketing");
    await userEvent.click(within(form).getByRole("radio", { name: "Another sender" }));
    await userEvent.click(within(form).getByRole("radio", { name: /^A list in the body, at/ }));
    await userEvent.click(within(form).getByRole("radio", { name: /^In each event, at/ }));
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    expect(await within(form).findByRole("textbox", { name: "The list's pointer", description: "A pointer into the body starts with /, like /items, at most 256 characters." })).toBeTruthy();
    expect(within(form).getByRole("textbox", { name: "The id's pointer", description: "A pointer starts with /, like /id, at most 256 characters." })).toBeTruthy();
    fields = ["id_header"];
    await userEvent.click(within(form).getByRole("radio", { name: /^In a header/ }));
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    expect(await within(form).findByRole("textbox", { name: "The id's header", description: /^A header's name: lowercase letters, digits and -/ })).toBeTruthy();
  });

  it("tells the workflows an endpoint starts while they load from when they couldn't be read", async () => {
    // 4c-3b's final review: both showed "–".
    api("editor", "development", {
      "GET /api/v1/t/t1/webhook-endpoints/e1/bindings": () => new Promise<Response>(() => undefined), // still loading
      "GET /api/v1/t/t1/webhook-endpoints/e2/bindings": () => json({ error: "http_error" }, 500),
    });
    await show();
    const row = async (name: string) => (await within(table()).findByText(name)).closest("tr")!;
    await vi.waitFor(async () => expect((await row("Ticketing")).textContent).toContain("couldn't be read"));
    expect((await row("Mist prod")).textContent).toContain("…");
    expect((await row("Mist prod")).textContent).not.toContain("–");
  });

  it("turns an endpoint off at once", async () => {
    const sent = api("editor", "development", { "PATCH /api/v1/t/t1/webhook-endpoints/e1": () => json({ ...ENDPOINT, enabled: false }) });
    await show();
    await userEvent.click(await within(table()).findByRole("switch", { name: "Mist prod" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ enabled: false }));
  });

  it("shows a viewer every endpoint, read only, and says why", async () => {
    api("viewer", "development");
    await show();
    expect(await screen.findByText(/Making and changing endpoints needs the editor role./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "＋ Endpoint" })).toBeNull();
    expect(within(table()).queryByRole("switch")).toBeNull();
    await userEvent.click(within(table()).getByRole("button", { name: "Mist prod, details" }));
    expect(within(table()).queryByRole("button", { name: "Rotate the token…" })).toBeNull();
    expect(within(table()).getByRole("button", { name: "Copy the path" })).toBeTruthy();
  });
});
