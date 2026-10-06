// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ReauthPrompt, SecurityPage } from "./Security";

it("asks again for a factor in a named form, not a dialog it isn't, with focus on its field", () => {
  render(<ReauthPrompt onDone={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("form", { name: "Confirm it's you" })).toBeTruthy();
  expect(document.activeElement).toBe(screen.getByLabelText("Authenticator code"));
});

const SESSION = {
  auth_methods: ["password", "totp"],
  csrf_token: "csrf-test",
  state: "active",
  user: { id: "u1", email: "admin@example.com", is_platform_admin: true },
};

/** The page, with the passkeys call answered by `passkeys` (a pending promise holds it in flight). */
function showSecurity(passkeys: () => Promise<Response>) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    if (path === "/api/v1/auth/passkeys") return passkeys();
    if (path === "/api/v1/auth/session") return Promise.resolve(new Response(JSON.stringify(SESSION), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify({ error: "unexpected" }), { status: 500 }));
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SecurityPage />
    </QueryClientProvider>,
  );
}

it("draws no empty passkey list while the list loads", () => {
  showSecurity(() => new Promise<Response>(() => {}));
  expect(screen.getByRole("heading", { name: "Passkeys" })).toBeTruthy();
  expect(screen.queryByRole("list")).toBeNull();
});

it("says so when there are no passkeys yet", async () => {
  showSecurity(() => Promise.resolve(new Response("[]", { status: 200 })));
  expect((await screen.findByRole("list")).textContent).toBe("No passkeys yet.");
});

it("says so when the passkeys can't be loaded, rather than showing an empty list", async () => {
  showSecurity(() => Promise.resolve(new Response(JSON.stringify({ error: "boom" }), { status: 500 })));
  expect((await screen.findByRole("alert")).textContent).toContain("Your passkeys couldn't be loaded");
  expect(screen.queryByRole("list")).toBeNull();
});
