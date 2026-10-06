// SPDX-License-Identifier: Apache-2.0
// The app's own routes, served from memory: what one tenant's screen holds never carries over to another's.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { routeTree } from "./router";

const SESSION = {
  auth_methods: ["password", "totp"],
  csrf_token: "csrf-test",
  state: "active",
  user: { id: "u1", email: "admin@example.com", is_platform_admin: true },
};
const TENANTS = [
  { id: "t1", name: "Acme Retail", slug: "acme-retail", role: "owner", require_passkey: false },
  { id: "t2", name: "Acme Lab", slug: "acme-lab", role: "owner", require_passkey: false },
];
const TYPES = [{ key: "mist", label: "Mist", config_schema: {}, secret_fields: ["api_token"], clouds: { global_01: "api.mist.com" } }];

let sent: { method: string; path: string; body: unknown }[];
/** Answers to hold back, by "METHOD /path": the test settles them. */
let held: Map<string, (r: Response) => void>;
let holding: Set<string>;

beforeEach(() => {
  sent = [];
  held = new Map();
  holding = new Set();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const key = `${request.method} ${path}`;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    if (holding.has(key)) return new Promise<Response>((resolve) => held.set(key, resolve));
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    if (key === "GET /api/v1/auth/session") return json(SESSION);
    if (key === "GET /api/v1/tenants") return json(TENANTS);
    if (key === "GET /api/v1/platform/status") return json({ environment: "production", production_runs: false });
    if (key === "GET /api/v1/connection-types") return json(TYPES);
    if (/^GET \/api\/v1\/t\/t[12]\/(?:connections|members)$/.test(key)) return json([]);
    if (/^GET \/api\/v1\/t\/t[12]\/workflows$/.test(key)) return json([]);
    if (key === "GET /api/v1/node-types") return json([]);
    const tenant = TENANTS.find((t) => key === `GET /api/v1/t/${t.id}`);
    if (tenant) return json(tenant);
    return json({ error: "unexpected" }, 500);
  });
});

function showApp(path: string) {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

async function draftConnection(name: string, token: string) {
  await userEvent.click(await screen.findByRole("button", { name: "Add Mist connection" }));
  await userEvent.type(screen.getByLabelText("Name"), name);
  await userEvent.type(screen.getByLabelText("Organization ID"), "6a1f6c34-6e8e-4b35-9a4c-1f0b8f1f2c11");
  await userEvent.type(screen.getByLabelText("API token"), token);
}

const posts = () => sent.filter((r) => r.method === "POST");

it("drops an unsaved connection draft when the tenant changes, so it can't be saved to the other tenant", async () => {
  const router = showApp("/t/t1/connections");
  await draftConnection("Acme Prod", "tok_acme");
  await act(() => router.navigate({ to: "/t/$tenantId/connections", params: { tenantId: "t2" } }));
  await screen.findByRole("button", { name: "Add Mist connection" });
  expect(screen.queryByRole("form", { name: "Add Mist connection" })).toBeNull();
  // The new tenant's form starts empty, and its save carries only what was typed for it.
  await draftConnection("Lab", "tok_lab");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(posts()).toEqual([{
    method: "POST",
    path: "/api/v1/t/t2/connections",
    body: {
      type: "mist", name: "Lab", config: { cloud: "global_01", org_id: "6a1f6c34-6e8e-4b35-9a4c-1f0b8f1f2c11" },
      secret: { api_token: "tok_lab" },
    },
  }]);
});

it("lets a save still on its way for one tenant leave the next tenant's form alone", async () => {
  holding.add("POST /api/v1/t/t1/connections");
  const router = showApp("/t/t1/connections");
  await draftConnection("Acme Prod", "tok_acme");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await vi.waitFor(() => expect(held.has("POST /api/v1/t/t1/connections")).toBe(true));
  await act(() => router.navigate({ to: "/t/$tenantId/connections", params: { tenantId: "t2" } }));
  await draftConnection("Lab", "tok_lab");
  // Acme's answer arrives now: it must not close or clear Lab's form.
  await act(async () => {
    held.get("POST /api/v1/t/t1/connections")!(new Response(JSON.stringify({ id: "c1" }), { status: 201 }));
    await new Promise((settled) => setTimeout(settled, 50)); // the old screen's success handlers have run
  });
  expect(screen.getByRole("form", { name: "Add Mist connection" })).toBeTruthy();
  expect(screen.getByLabelText("Name")).toHaveProperty("value", "Lab");
  expect(screen.getByLabelText("API token")).toHaveProperty("value", "tok_lab");
  expect(posts().map((r) => r.path)).toEqual(["/api/v1/t/t1/connections"]);
});

it("drops a member being added when the tenant changes", async () => {
  const router = showApp("/t/t1/settings/members");
  await userEvent.type(await screen.findByLabelText("Email"), "new@corp.test");
  await act(() => router.navigate({ to: "/t/$tenantId/settings/members", params: { tenantId: "t2" } }));
  await screen.findByRole("heading", { name: /Settings · Acme Lab/ });
  expect(await screen.findByLabelText("Email")).toHaveProperty("value", "");
});

it("opens a tenant on its workflows", async () => {
  const router = showApp("/t/t1");
  expect(await screen.findByRole("heading", { level: 1, name: "Workflows" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/t/t1/workflows");
});

it("opens a tenant chosen from the tenants page on its workflows (4b ruling 19; ledger M6)", async () => {
  const router = showApp("/tenants");
  await userEvent.click(await screen.findByRole("link", { name: "Acme Lab" }));
  expect(await screen.findByRole("heading", { level: 1, name: "Workflows" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/t/t2/workflows");
});
