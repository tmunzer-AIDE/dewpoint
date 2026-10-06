// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";
import { ThemeSelect } from "./ThemeSelect";

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

it("follows the OS until told otherwise", () => {
  render(<ThemeSelect />);
  expect(screen.getByRole("combobox", { name: "Theme" })).toHaveProperty("value", "system");
  expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
});

it("applies and remembers a chosen theme, and forgets it when the OS is chosen again", async () => {
  render(<ThemeSelect />);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Theme" }), "dark");
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  expect(localStorage.getItem("dewpoint.theme")).toBe("dark");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Theme" }), "system");
  expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  expect(localStorage.getItem("dewpoint.theme")).toBeNull();
});

it("starts from the remembered theme", () => {
  localStorage.setItem("dewpoint.theme", "light");
  render(<ThemeSelect />);
  expect(screen.getByRole("combobox", { name: "Theme" })).toHaveProperty("value", "light");
  expect(document.documentElement.getAttribute("data-theme")).toBe("light");
});
