// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkflowsPage } from "./Workflows";

const NOW = Date.parse("2026-10-06T12:00:00Z");
const row = (over: Record<string, unknown>) => ({
  id: "w1", name: "Nightly", enabled: true, draft_revision: 3, active_version_id: "v2", active_version_number: 2,
  executable: true, blocked_by: [], created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-06T10:00:00Z",
  unpublished_changes: false, last_run: { status: "succeeded", at: "2026-10-06T11:48:00Z" }, last_simulation: null,
  runs_24h: { live: 4, simulate: 0 }, needs_attention: [], ...over,
});  // prettier-ignore
const ROWS = [
  row({}),
  row({ id: "w2", name: "Triage", enabled: false, unpublished_changes: true, runs_24h: { live: 1, simulate: 2 },
        last_run: { status: "failed", at: "2026-10-06T11:00:00Z" }, last_simulation: { status: "succeeded", at: "2026-10-06T11:30:00Z" },
        needs_attention: ["last_run_failed"] }),
  row({ id: "w3", name: "Sketch", active_version_id: null, active_version_number: null, executable: null,
        unpublished_changes: true, last_run: null, runs_24h: { live: 0, simulate: 0 } }),
];  // prettier-ignore

let role = "editor";
let sent: { method: string; path: string; body: unknown }[];
let patchAnswer: Response | null;
let exportAnswer: Response | null;

beforeEach(() => {
  role = "editor";
  sent = [];
  patchAnswer = null;
  exportAnswer = null;
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    if (request.method === "PATCH") return patchAnswer ?? new Response(JSON.stringify({ ...ROWS[0], enabled: false, warnings: [] }));
    if (path === "/api/v1/t/t1") return new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }));
    if (path === "/api/v1/t/t1/workflows/w2/export") return exportAnswer ?? new Response(JSON.stringify({ format: "dewpoint.workflow", format_version: 1, name: "Triage", graph: {}, bindings: [] }));
    return new Response(JSON.stringify(ROWS));
  });
});

async function show() {
  const root = createRootRoute({ component: () => <WorkflowsPage tenantId="t1" /> });
  const editor = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId", component: () => <p>editor</p> });
  const router = createRouter({ routeTree: root.addChildren([editor]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("link", { name: "Nightly" });
  return router;
}

const rowOf = (name: string) => screen.getByRole("link", { name }).closest("tr")!;

it("shows each workflow's version, last run and last 24 hours in words", async () => {
  await show();
  expect(rowOf("Nightly").textContent).toContain("v2");
  expect(rowOf("Nightly").textContent).toContain("Succeeded · 12 min ago");
  expect(rowOf("Triage").textContent).toContain("v2 · unpublished changes");
  expect(rowOf("Triage").textContent).toContain("Failed · 1 h ago");
  expect(rowOf("Triage").textContent).toContain("Simulated: Succeeded · 30 min ago"); // apart, never the last run
  expect(rowOf("Triage").textContent).toContain("1 +2 simulated");
  expect(rowOf("Sketch").textContent).toContain("Not published");
  expect(rowOf("Sketch").textContent).toContain("No runs yet");
});

it("filters by state, with counts, and by name", async () => {
  await show();
  const filters = screen.getByRole("group", { name: "Show" });
  expect(within(filters).getAllByRole("button").map((b) => b.textContent)).toEqual([
    "All 3", "Published 2", "Unpublished changes 2", "Needs attention 1",
  ]);  // prettier-ignore
  await userEvent.click(within(filters).getByRole("button", { name: "Unpublished changes 2" }));
  expect(screen.getAllByRole("link").map((l) => l.textContent)).toEqual(["Triage", "Sketch"]); // never published counts
  await userEvent.click(within(filters).getByRole("button", { name: "Needs attention 1" }));
  expect(screen.queryByRole("link", { name: "Nightly" })).toBeNull();
  expect(screen.getByRole("link", { name: "Triage" })).toBeTruthy();
  await userEvent.click(within(filters).getByRole("button", { name: "All 3" }));
  await userEvent.type(screen.getByLabelText("Filter by name"), "sk");
  expect(screen.getAllByRole("link").map((l) => l.textContent)).toEqual(["Sketch"]);
});

it("lets a publisher switch a workflow off, and says why one can't be switched on", async () => {
  await show();
  await userEvent.click(await within(rowOf("Nightly")).findByRole("switch", { name: "Enable Nightly" }));
  expect(sent.find((r) => r.method === "PATCH")).toEqual({ method: "PATCH", path: "/api/v1/t/t1/workflows/w1", body: { enabled: false } });
  patchAnswer = new Response(
    JSON.stringify({ error: "not_enableable", diagnostics: [{ code: "lifecycle.retired", message: "testkit.echo@1 is retired.", node: null, field: null, fix: null, severity: "error" }] }),
    { status: 422 },
  );  // prettier-ignore
  await userEvent.click(within(rowOf("Triage")).getByRole("switch", { name: "Enable Triage" }));
  expect(sent.filter((r) => r.method === "PATCH").at(-1)?.body).toEqual({ enabled: true });
  expect((await screen.findByRole("alert")).textContent).toContain("Triage can't be switched on: testkit.echo@1 is retired.");
});

it("shows a viewer the state, not the switch", async () => {
  role = "viewer";
  await show();
  await vi.waitFor(() => expect(sent.some((r) => r.path === "/api/v1/t/t1")).toBe(true)); // the role is known
  await vi.waitFor(() => expect(rowOf("Nightly").textContent).toContain("On"));
  expect(within(rowOf("Nightly")).queryByRole("switch")).toBeNull();
});

it("exports a workflow as a file named after it", async () => {
  const createObjectURL = vi.fn(() => "blob:test");
  Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  await show();
  await userEvent.click(within(rowOf("Triage")).getByRole("button", { name: "Actions for Triage" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Export" }));
  await vi.waitFor(() => expect(click).toHaveBeenCalled());
  expect((click.mock.instances[0] as unknown as HTMLAnchorElement).download).toBe("triage.dewpoint.json");
});

it("says why a workflow can't be exported as a portable file", async () => {
  exportAnswer = new Response(
    JSON.stringify({ error: "not_portable", problems: [{ reason: "unknown_type", binding: null, node: "n1", field: null }] }),
    { status: 422 },
  );  // prettier-ignore
  await show();
  await userEvent.click(within(rowOf("Triage")).getByRole("button", { name: "Actions for Triage" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Export" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Triage can't be exported as a portable file: it has steps of a type this server doesn't know. Open it to download the draft as it is.",
  );
});

it("offers New workflow to editors, and opens it when asked by the URL", async () => {
  await show();
  await userEvent.click(await screen.findByRole("button", { name: "New workflow" }));
  expect(screen.getByRole("dialog", { name: "New workflow" })).toBeTruthy();
});

it("offers no New workflow to a viewer", async () => {
  role = "viewer";
  await show();
  await screen.findByRole("link", { name: "Nightly" });
  expect(screen.queryByRole("button", { name: "New workflow" })).toBeNull();
});
