// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

/** The page, its calls answered by `answers` ("METHOD /path"); the session is signed in, there are no passkeys. */
function showSecurity(answers: Record<string, () => Promise<Response>> = {}) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const request = input as Request;
    const key = `${request.method} ${new URL(request.url).pathname}`;
    const answer = answers[key];
    if (answer) return answer();
    if (key === "GET /api/v1/auth/session") return json(SESSION);
    if (key === "GET /api/v1/auth/passkeys") return json([]);
    return json({ error: "unexpected" }, 500);
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SecurityPage />
    </QueryClientProvider>,
  );
}

it("draws no empty passkey list while the list loads", () => {
  showSecurity({ "GET /api/v1/auth/passkeys": () => new Promise<Response>(() => {}) });
  expect(screen.getByRole("heading", { name: "Passkeys" })).toBeTruthy();
  expect(screen.queryByRole("list")).toBeNull();
});

it("says so when there are no passkeys yet", async () => {
  showSecurity();
  expect((await screen.findByRole("list")).textContent).toBe("No passkeys yet.");
});

it("says so when the passkeys can't be loaded, rather than showing an empty list", async () => {
  showSecurity({ "GET /api/v1/auth/passkeys": () => json({ error: "boom" }, 500) });
  expect((await screen.findByRole("alert")).textContent).toContain("Your passkeys couldn't be loaded");
  expect(screen.queryByRole("list")).toBeNull();
});

// The button that opens a step goes away with it: focus moves to the step, never to the page's body.
it("keeps focus with the authenticator setup when its button gives way to it", async () => {
  showSecurity();
  await userEvent.click(screen.getByRole("button", { name: "Set up or replace authenticator app" }));
  expect(document.activeElement).toBe(screen.getByTestId("totp-start"));
});

it("puts focus on the code field once the authenticator setup starts", async () => {
  showSecurity({
    "POST /api/v1/auth/mfa/totp/enroll": () =>
      json({ otpauth_uri: "otpauth://totp/Dewpoint:admin@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Dewpoint" }),
  });
  await userEvent.click(screen.getByRole("button", { name: "Set up or replace authenticator app" }));
  await userEvent.click(screen.getByTestId("totp-start"));
  expect(document.activeElement).toBe(await screen.findByLabelText("Code from the app"));
});

it("gives focus back to the button that asked for re-authentication when the prompt is cancelled", async () => {
  showSecurity({ "POST /api/v1/auth/mfa/totp/enroll": () => json({ error: "reauth_required" }, 403) });
  await userEvent.click(screen.getByRole("button", { name: "Set up or replace authenticator app" }));
  const start = screen.getByTestId("totp-start");
  await userEvent.click(start);
  await screen.findByRole("form", { name: "Confirm it's you" });
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("form", { name: "Confirm it's you" })).toBeNull();
  expect(document.activeElement).toBe(start);
});
