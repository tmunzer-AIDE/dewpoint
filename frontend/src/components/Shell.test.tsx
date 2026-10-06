// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Shell } from "./Shell";

const TENANTS = [{ id: "t1", name: "Acme Retail", slug: "acme-retail", role: "admin", require_passkey: false }];

let environment: string | null = "production";
let statusFails = false;

beforeEach(() => {
  environment = "production";
  statusFails = false;
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = input instanceof Request ? input.url : input.toString();
    if (statusFails && url.endsWith("/api/v1/platform/status")) {
      return Promise.resolve(new Response(JSON.stringify({ error: "internal_error" }), { status: 500 }));
    }
    const body = url.endsWith("/api/v1/platform/status")
      ? { environment, production_runs: false }
      : TENANTS;
    return Promise.resolve(new Response(JSON.stringify(body)));
  });
});

async function renderAt(path: string) {
  const root = createRootRoute({ component: Shell });
  const page = () => <p>page</p>;
  const children = ["/t/$tenantId/connections", "/t/$tenantId/settings/members", "/tenants", "/account/security"].map((p) =>
    createRoute({ getParentRoute: () => root, path: p, component: page }),
  );
  const router = createRouter({
    routeTree: root.addChildren(children),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByText("page");
}

it("puts the wordmark and the main navigation on the rail", async () => {
  await renderAt("/t/t1/connections");
  const nav = screen.getByRole("navigation", { name: "Main" });
  expect(nav.closest("[data-surface='rail']")).not.toBeNull();
  expect(screen.getByText("Dewpoint")).toBeTruthy();
});

it("marks the current page by weight, ink and background, not by colour alone", async () => {
  await renderAt("/t/t1/connections");
  const current = screen.getByRole("link", { name: "Connections" });
  expect(current.getAttribute("aria-current")).toBe("page");
  expect(current.className).toMatch(/\bbg-rail-active\b/);
  expect(current.className).toMatch(/\bfont-semibold\b/);
  expect(current.className).toMatch(/\btext-rail-ink-strong\b/);
});

it("offers a tenant's pages only once a tenant is chosen", async () => {
  await renderAt("/tenants");
  expect(screen.queryByRole("link", { name: "Connections" })).toBeNull();
});

it("keeps the tenant switcher, the ⌘K palette, Security and Sign out in the header", async () => {
  await renderAt("/t/t1/connections");
  const header = screen.getByRole("banner");
  expect(header.contains(await screen.findByTestId("tenant-switcher"))).toBe(true);
  expect(header.contains(screen.getByRole("button", { name: /Search or jump to/ }))).toBe(true);
  expect(header.contains(screen.getByRole("link", { name: "Security" }))).toBe(true);
  expect(header.contains(screen.getByRole("button", { name: "Sign out" }))).toBe(true);
});

it("says so on every screen when the deployment is a development one (engine 2b spec §2.1)", async () => {
  environment = "development";
  await renderAt("/t/t1/connections");
  const note = await screen.findByRole("note", { name: "Deployment" });
  expect(note.textContent).toContain("Development deployment");
});

it("shows no deployment note in production", async () => {
  await renderAt("/t/t1/connections");
  await screen.findByTestId("tenant-switcher");
  expect(screen.queryByRole("note", { name: "Deployment" })).toBeNull();
});

it("offers Settings beside Connections, current on its pages", async () => {
  await renderAt("/t/t1/settings/members");
  const settings = screen.getByRole("link", { name: "Settings" });
  expect(settings.getAttribute("aria-current")).toBe("page");
  expect(screen.getByRole("link", { name: "Connections" }).getAttribute("aria-current")).toBeNull();
});

it("says so when the deployment's environment can't be read, rather than staying silent", async () => {
  statusFails = true;
  await renderAt("/t/t1/connections");
  const note = await screen.findByRole("note", { name: "Deployment" }, { timeout: 4000 });
  expect(note.textContent).toContain("couldn't be read");
});

it("offers a theme choice in the header: the OS's, light or dark (D6)", async () => {
  await renderAt("/t/t1/connections");
  const theme = screen.getByRole("combobox", { name: "Theme" });
  expect(screen.getByRole("banner").contains(theme)).toBe(true);
});

