// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { MembersPage } from "./Members";

type Route = { status: number; body?: unknown };
let routes: Record<string, Route>;
let sent: { method: string; path: string; body: unknown }[];

const MEMBERS = [
  { user_id: "u1", email: "owner@corp.test", role: "owner" },
  { user_id: "u2", email: "ed@corp.test", role: "editor" },
];

function asCaller(role: string) {
  routes = {
    "GET /api/v1/t/t1": { status: 200, body: { id: "t1", name: "Acme Retail", slug: "acme-retail", require_passkey: false, role } },
    "GET /api/v1/t/t1/members": { status: 200, body: MEMBERS },
  };
}

beforeEach(() => {
  sent = [];
  asCaller("admin");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    const route = routes[`${request.method} ${path}`] ?? { status: 500, body: { error: "unexpected" } };
    return new Response(route.status === 204 ? null : JSON.stringify(route.body ?? {}), { status: route.status });
  });
});

function show() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MembersPage tenantId="t1" />
    </QueryClientProvider>,
  );
}

it("lists the tenant's members and their roles", async () => {
  show();
  const row = (await screen.findByText("ed@corp.test")).closest("tr")!;
  expect(within(row).getByLabelText("Role of ed@corp.test")).toHaveProperty("value", "editor");
  expect(screen.getByText("owner@corp.test")).toBeTruthy();
});

it("lets a viewer read the list, and nothing else", async () => {
  asCaller("viewer");
  show();
  await screen.findByText("ed@corp.test");
  expect(screen.queryByRole("button", { name: /Add member/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  expect(screen.queryByRole("combobox")).toBeNull();
});

it("adds a member by email, and says plainly when no account has that email", async () => {
  routes["POST /api/v1/t/t1/members"] = { status: 404, body: { error: "user_not_found" } };
  show();
  await screen.findByText("ed@corp.test");
  await userEvent.type(screen.getByLabelText("Email"), "new@corp.test");
  await userEvent.selectOptions(screen.getByLabelText("Role"), "operator");
  await userEvent.click(screen.getByRole("button", { name: "Add member" }));
  expect(sent.find((r) => r.method === "POST")).toEqual({
    method: "POST",
    path: "/api/v1/t/t1/members",
    body: { email: "new@corp.test", role: "operator" },
  });
  expect((await screen.findByRole("alert")).textContent).toContain("No Dewpoint account has that email");
});

it("changes a role, and explains a refusal to drop the last owner", async () => {
  routes["PATCH /api/v1/t/t1/members/u1"] = { status: 409, body: { error: "last_owner" } };
  show();
  await userEvent.selectOptions(await screen.findByLabelText("Role of owner@corp.test"), "admin");
  expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ role: "admin" });
  expect((await screen.findByRole("alert")).textContent).toContain("at least one owner");
});

it("removes a member only after confirming, by name", async () => {
  routes["DELETE /api/v1/t/t1/members/u2"] = { status: 204 };
  show();
  const row = (await screen.findByText("ed@corp.test")).closest("tr")!;
  await userEvent.click(within(row).getByRole("button", { name: "Remove ed@corp.test" }));
  expect(sent.some((r) => r.method === "DELETE")).toBe(false);
  const confirm = screen.getByRole("dialog", { name: "Remove a member" });
  expect(confirm.textContent).toContain("ed@corp.test");
  await userEvent.click(within(confirm).getByRole("button", { name: "Remove" }));
  expect(sent.find((r) => r.method === "DELETE")?.path).toBe("/api/v1/t/t1/members/u2");
  // The row and its button are gone: focus goes to the list's heading, not to the page's body.
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Members" })));
});

it("names the page in the browser's title, and heads its list by what it holds", async () => {
  show();
  await screen.findByText("ed@corp.test");
  expect(document.title).toBe("Members & roles · Dewpoint");
  expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Members");
});

it("says so when the members can't be loaded, rather than showing an empty table", async () => {
  routes["GET /api/v1/t/t1/members"] = { status: 500, body: { error: "boom" } };
  show();
  expect((await screen.findByRole("alert")).textContent).toContain("The members couldn't be loaded");
  expect(screen.queryByRole("table")).toBeNull();
});
