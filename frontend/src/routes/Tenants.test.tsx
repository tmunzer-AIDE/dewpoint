// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { TenantsPage } from "./Tenants";

const SESSION = {
  auth_methods: ["password", "totp"],
  csrf_token: "csrf-test",
  state: "active",
  user: { id: "u1", email: "admin@example.com", is_platform_admin: true },
};

it("says so when the tenants can't be loaded, rather than showing an empty table", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    if (path === "/api/v1/auth/session") return Promise.resolve(new Response(JSON.stringify(SESSION), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify({ error: "boom" }), { status: 500 }));
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TenantsPage />
    </QueryClientProvider>,
  );
  expect((await screen.findByRole("alert")).textContent).toContain("Your tenants couldn't be loaded");
  expect(screen.queryByRole("table")).toBeNull();
});
