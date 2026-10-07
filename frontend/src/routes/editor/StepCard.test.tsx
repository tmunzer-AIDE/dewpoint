// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { StepCardBody, typeCode } from "./StepCard";

const node = { id: "n1", key: "get_device", type: "flow.transform@1" };
const TRANSFORM = { ref: "flow.transform@1", type: "flow.transform", title: "Transform" } as never;

it("names a step by its key, its type and its problems, its code a plain mono label (no tinted tile)", () => {
  render(<StepCardBody node={node} type={TRANSFORM} problems={{ errors: 2, warnings: 0 }} separate={1} current={false} tabIndex={0} onOpen={vi.fn()} />);
  const card = screen.getByRole("button", { name: "get_device, Transform, 2 problems, 1 expression runs as a separate step" });
  expect(card.getAttribute("data-item")).toBe("node:n1");
  expect(card.textContent).toContain("MAP");
  expect(card.innerHTML).not.toMatch(/bg-accent-soft/);
});

it("says a step's type is unknown, and draws its card dashed", () => {
  render(<StepCardBody node={{ ...node, type: "vendor.thing@3" }} type={undefined} problems={{ errors: 0, warnings: 0 }} separate={0} current={false} tabIndex={-1} onOpen={vi.fn()} />);
  const card = screen.getByRole("button", { name: "get_device, Unknown step type vendor.thing@3" });
  expect(card.className).toMatch(/border-dashed/);
});

it("marks the step whose panel is open with a 2 px accent border (1c), never the focus ring's outline nor a halo", () => {
  render(<StepCardBody node={node} type={TRANSFORM} problems={{ errors: 0, warnings: 0 }} separate={0} current tabIndex={0} onOpen={vi.fn()} />);
  const card = screen.getByRole("button");
  expect(card.className).toMatch(/\bborder-2\b/);
  expect(card.className).toMatch(/\bborder-accent\b/);
  // The focus ring is the one 2 px outline (theme.css): an open step that wore it too would look focused when it isn't.
  expect(card.className).not.toMatch(/\boutline-/);
  expect(card.className).not.toMatch(/ring-[3-9]|shadow-\[/);
});

it("codes control steps by what they do and actions by their plugin", () => {
  expect([typeCode("flow.if@1"), typeCode("flow.loop@1"), typeCode("testkit.http_call@1")]).toEqual(["IF", "LOOP", "TESTKI"]);
});

it("takes the pointer even where React Flow turns a node's off (a step a viewer can't drag, the start card)", () => {
  render(<StepCardBody node={node} type={TRANSFORM} problems={{ errors: 0, warnings: 0 }} separate={0} current={false} tabIndex={0} onOpen={vi.fn()} />);
  // @xyflow/react 12.12.0 sets `pointer-events: none` on a node that is neither selectable nor draggable (ledger M11).
  expect(screen.getByRole("button").className).toMatch(/(?:^|\s)pointer-events-auto(?:\s|$)/);
});
