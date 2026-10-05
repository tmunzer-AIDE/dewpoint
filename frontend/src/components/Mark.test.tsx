// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Mark, Wordmark } from "./Mark";

it("draws the mark as decoration, hidden from assistive technology", () => {
  const { container } = render(<Mark />);
  const svg = container.querySelector("svg");
  expect(svg?.getAttribute("aria-hidden")).toBe("true");
  expect(svg?.querySelectorAll("circle")).toHaveLength(2);
});

it("names the product and what it is for, as text", () => {
  render(<Wordmark />);
  expect(screen.getByText("Dewpoint")).toBeTruthy();
  expect(screen.getByText("for Juniper Mist")).toBeTruthy();
});
