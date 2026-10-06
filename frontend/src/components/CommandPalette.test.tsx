// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

const TENANTS = [
  { id: "t1", name: "Acme Retail", slug: "acme-retail", role: "admin", require_passkey: false },
  { id: "t2", name: "Acme Lab", slug: "acme-lab", role: "editor", require_passkey: false },
];

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(new Response(JSON.stringify(TENANTS))));
});

async function renderAt(path: string) {
  const root = createRootRoute({ component: () => <><CommandPalette /><Outlet /></> });
  const page = (name: string) => () => <p>{name}</p>;
  const routes = [
    createRoute({ getParentRoute: () => root, path: "/t/$tenantId/connections", component: page("connections page") }),
    createRoute({ getParentRoute: () => root, path: "/account/security", component: page("security page") }),
    createRoute({ getParentRoute: () => root, path: "/tenants", component: page("tenants page") }),
    createRoute({
      getParentRoute: () => root,
      path: "/t/$tenantId/workflows",
      component: page("workflows page"),
      validateSearch: (s: Record<string, unknown>) => (s.new === true || s.new === "true" ? { new: true } : {}),
    }),
    createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId", component: page("editor page") }),
  ];
  const router = createRouter({ routeTree: root.addChildren(routes), history: createMemoryHistory({ initialEntries: [path] }) });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("button", { name: /Search or jump to/ });
  return router;
}

const dialog = () => document.querySelector("dialog")!;

it("opens with ⌘K or Ctrl+K, its search field focused", async () => {
  await renderAt("/t/t1/connections");
  expect(dialog().hasAttribute("open")).toBe(false);
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  expect(dialog().hasAttribute("open")).toBe(true);
  expect(document.activeElement).toBe(screen.getByRole("combobox"));
  act(() => dialog().close()); // Escape, in a browser: its close event is handled before the next key
  fireEvent.keyDown(document, { key: "K", ctrlKey: true });
  expect(dialog().hasAttribute("open")).toBe(true);
});

it("names its trigger and its shortcut", async () => {
  await renderAt("/t/t1/connections");
  const trigger = screen.getByRole("button", { name: /Search or jump to/ });
  expect(trigger.getAttribute("aria-keyshortcuts")).toBe("Meta+K Control+K");
  await userEvent.click(trigger);
  expect(dialog().hasAttribute("open")).toBe(true);
});

it("lists the pages and every tenant, and filters as you type", async () => {
  await renderAt("/t/t1/connections");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await screen.findByRole("option", { name: /Acme Lab/ });
  const names = () => screen.getAllByRole("option").map((o) => o.textContent);
  expect(names()).toEqual(expect.arrayContaining(["Connections", "Security", "All tenants"]));
  await userEvent.type(screen.getByRole("combobox"), "secur");
  expect(names()).toEqual(["Security"]);
});

it("goes where the chosen item points, then closes", async () => {
  const router = await renderAt("/t/t1/connections");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await screen.findByRole("option", { name: /Acme Lab/ });
  await userEvent.type(screen.getByRole("combobox"), "secur{Enter}");
  await screen.findByText("security page");
  expect(router.state.location.pathname).toBe("/account/security");
  expect(dialog().hasAttribute("open")).toBe(false);
});

it("outlines the selected option, which never takes focus itself (WCAG 1.4.11)", async () => {
  await renderAt("/t/t1/connections");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  const selected = (await screen.findAllByRole("option")).find((o) => o.getAttribute("data-selected") === "true")!;
  expect(selected.className).toMatch(/data-\[selected=true\]:outline-2\b/);
  expect(selected.className).toMatch(/data-\[selected=true\]:outline-focus\b/);
});

it("offers a tenant's pages only once a tenant is chosen", async () => {
  await renderAt("/tenants");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await screen.findByRole("option", { name: /Acme Lab/ });
  expect(screen.queryByRole("option", { name: "Connections" })).toBeNull();
});

it("lists the tenant's workflows, opens one, and starts a new one", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    const body = path === "/api/v1/t/t1/workflows" ? [{ id: "w1", name: "Nightly report" }] : TENANTS;
    return Promise.resolve(new Response(JSON.stringify(body)));
  });
  const router = await renderAt("/t/t1/connections");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await userEvent.click(await screen.findByRole("option", { name: "Nightly report" }));
  expect(router.state.location.pathname).toBe("/t/t1/workflows/w1");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await userEvent.click(await screen.findByRole("option", { name: "New workflow" }));
  expect(router.state.location.pathname).toBe("/t/t1/workflows");
  expect(router.state.location.search).toEqual({ new: true });
});

it("opens a tenant on its workflows", async () => {
  const router = await renderAt("/account/security");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await userEvent.click(await screen.findByRole("option", { name: /Acme Lab/ }));
  expect(router.state.location.pathname).toBe("/t/t2/workflows");
});
