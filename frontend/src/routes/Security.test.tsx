// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ReauthPrompt } from "./Security";

it("asks again for a factor in a named form, not a dialog it isn't, with focus on its field", () => {
  render(<ReauthPrompt onDone={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("form", { name: "Confirm it's you" })).toBeTruthy();
  expect(document.activeElement).toBe(screen.getByLabelText("Authenticator code"));
});
