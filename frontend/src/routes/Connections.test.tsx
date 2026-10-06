// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ConnectionsPage } from "./Connections";

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    const body = path === "/api/v1/connection-types"
      ? [{ key: "mist", label: "Mist", config_schema: {}, secret_fields: ["api_token"], clouds: { global_01: "api.mist.com" } }]
      : [];
    return Promise.resolve(new Response(JSON.stringify(body)));
  });
});

function show() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ConnectionsPage tenantId="t1" />
    </QueryClientProvider>,
  );
}

it("names the page in the browser's title", async () => {
  show();
  await screen.findByText("No Mist connection yet.");
  expect(document.title).toBe("Connections · Dewpoint");
});

it("forgets a typed token on Cancel, and gives focus back to the button that opened the form", async () => {
  show();
  const add = await screen.findByRole("button", { name: "Add Mist connection" });
  await userEvent.click(add);
  await userEvent.type(screen.getByLabelText("API token"), "tok_secret");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(document.activeElement).toBe(add);
  await userEvent.click(add);
  expect(screen.getByLabelText("API token")).toHaveProperty("value", "");
});

it("says so when the connections can't be loaded, rather than showing an empty table", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    const failed = path === "/api/v1/t/t1/connections";
    return Promise.resolve(new Response(failed ? JSON.stringify({ error: "boom" }) : "[]", { status: failed ? 500 : 200 }));
  });
  show();
  expect((await screen.findByRole("alert")).textContent).toContain("The connections couldn't be loaded");
  expect(screen.queryByRole("table")).toBeNull();
});
