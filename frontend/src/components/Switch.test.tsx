// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Switch } from "./Switch";

it("is a named switch that says its state, and toggles from the keyboard", async () => {
  const onCheckedChange = vi.fn();
  render(<Switch checked={false} onCheckedChange={onCheckedChange} label="Enable Nightly" />);
  const toggle = screen.getByRole("switch", { name: "Enable Nightly" });
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  toggle.focus();
  await userEvent.keyboard(" ");
  expect(onCheckedChange).toHaveBeenCalledWith(true);
});

it("is a rounded rectangle, not a pill (outline §6)", () => {
  render(<Switch checked onCheckedChange={vi.fn()} label="Enable" />);
  expect(screen.getByRole("switch").className).not.toMatch(/rounded-full/);
});
