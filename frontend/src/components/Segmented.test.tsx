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

it("separates its options by the group's own 1 px gaps, never a border on one side, so a wrapped row starts clean", () => {
  render(
    <Segmented
      label="Show"
      value="all"
      onChange={vi.fn()}
      options={[{ value: "all", label: "All", count: 6 }, { value: "draft", label: "Unpublished changes", count: 2 }]}
    />,
  );
  // At 320 px the options wrap (WCAG 1.4.10): a left border would open each new row with a stray line, and rows of
  // unequal width would leave the group ragged. The gaps show the group's line colour; the options fill each row.
  expect(screen.getByRole("group", { name: "Show" }).className).toMatch(/\bgap-px\b/);
  for (const option of screen.getAllByRole("button")) {
    expect(option.className).not.toMatch(/\bborder-[lrtb]\b/);
    expect(option.className).toMatch(/\bgrow\b/);
  }
});
