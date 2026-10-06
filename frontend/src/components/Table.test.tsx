// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Table, Td, Th } from "./Table";

it("lets the keyboard scroll a table its screen is too narrow for: the frame is a named region that takes focus", () => {
  render(
    <Table label="Mist connections">
      <thead><tr><Th>Name</Th></tr></thead>
      <tbody><tr><Td>No Mist connection yet.</Td></tr></tbody>
    </Table>,
  );
  const frame = screen.getByRole("region", { name: "Mist connections" });
  expect(frame.tabIndex).toBe(0);
  expect(frame.querySelector("table")).toBeTruthy();
});
