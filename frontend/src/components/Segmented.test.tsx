// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Segmented } from "./Segmented";

it("is a named group of buttons, the chosen one pressed, each with its count", async () => {
  const onChange = vi.fn();
  render(
    <Segmented
      label="Show"
      value="all"
      onChange={onChange}
      options={[{ value: "all", label: "All", count: 6 }, { value: "attention", label: "Needs attention", count: 1 }]}
    />,
  );
  expect(screen.getByRole("group", { name: "Show" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "All 6" }).getAttribute("aria-pressed")).toBe("true");
  await userEvent.click(screen.getByRole("button", { name: "Needs attention 1" }));
  expect(onChange).toHaveBeenCalledWith("attention");
});
