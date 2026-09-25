// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { LoginForm } from "./Login";

it("shows a generic error and never echoes the password", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ error: "invalid_credentials" }), { status: 401 }),
  );
  const onDone = vi.fn();
  render(<LoginForm onDone={onDone} />);
  await userEvent.type(screen.getByTestId("login-email"), "a@corp.test");
  await userEvent.type(screen.getByTestId("login-password"), "hunter2-secret");
  await userEvent.click(screen.getByTestId("login-submit"));
  expect((await screen.findByRole("alert")).textContent).toBe("Email or password is incorrect.");
  expect(document.body.textContent).not.toContain("hunter2-secret");
  expect(onDone).not.toHaveBeenCalled();
});
