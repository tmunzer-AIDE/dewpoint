// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Field, Select } from "./Field";

it("labels its input and describes it by its hint", () => {
  render(<Field label="Slug" hint="Lowercase letters, digits and dashes." />);
  const input = screen.getByLabelText("Slug");
  expect(input.getAttribute("aria-describedby")).toBeTruthy();
  expect(document.getElementById(input.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Lowercase letters, digits and dashes.",
  );
  expect(input.getAttribute("aria-invalid")).toBe("false");
});

it("draws its boundary at 3:1 (line-control), and red with its message when invalid", () => {
  const { rerender } = render(<Field label="Org ID" />);
  expect(screen.getByLabelText("Org ID").className).toContain("border-line-control");
  rerender(<Field label="Org ID" hint="36 characters." error="Enter the UUID from Mist." />);
  const input = screen.getByLabelText("Org ID");
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(input.className).toContain("border-danger");
  const described = input.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)?.textContent);
  expect(described).toEqual(["36 characters.", "Enter the UUID from Mist."]);
});

it("draws its placeholder in muted ink, 4.5:1, since a placeholder may carry the format", () => {
  render(<Field label="Org ID" placeholder="36-character UUID" />);
  expect(screen.getByLabelText("Org ID").className).toContain("placeholder:text-muted");
});

it("gives a select the same label and boundary", () => {
  render(
    <Select label="Mist cloud" value="a" onChange={() => undefined}>
      <option value="a">api.mist.com</option>
    </Select>,
  );
  const select = screen.getByLabelText("Mist cloud");
  expect(select.tagName).toBe("SELECT");
  expect(select.className).toContain("border-line-control");
});
