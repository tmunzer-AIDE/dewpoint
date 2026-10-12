// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { StepOptions } from "../../../lib/config";
import type { GraphNode } from "../../../lib/workflows";
import { DELAY } from "../../../test/nodeTypes";
import { ErrorHandling, chipText } from "./ErrorHandling";
import { fakeApi, showFields } from "./harness";

beforeEach(() => {
  fakeApi({});
});
afterEach(() => {
  vi.restoreAllMocks();
});

const node = (options?: StepOptions): GraphNode => ({ id: "n1", key: "wait", type: "flow.delay@1", ...(options ? { options } : {}) });

it("says what a failure does in words, and the limits the step sets", () => {
  expect(chipText(node(), DELAY)).toBe("On error: fail the run");
  expect(chipText(node({ on_error: "port", max_attempts: 5, timeout_s: 60 }), DELAY)).toBe("On error: route to the error port · 5 attempts");
  expect(chipText(node({ on_error: "continue", max_attempts: 1, timeout_s: 30 }), DELAY)).toBe("On error: continue · 1 attempt · 30 s");
});

it("sets what a failure does, and leaves an emptied limit to the type", async () => {
  const { node: step } = showFields(DELAY, { options: { max_attempts: 5 } }, <ErrorHandling />);
  await userEvent.selectOptions(screen.getByLabelText("When it fails"), "Continue with the next step");
  expect(step().options).toEqual({ max_attempts: 5, on_error: "continue" });
  expect(screen.getByText("If empty: 3.")).toBeTruthy();
  await userEvent.clear(screen.getByLabelText("Attempts"));
  expect(step().options).toEqual({ on_error: "continue" });
});

it("holds attempts and a timeout the graph's format refuses, writing neither", async () => {
  const { node: step, held } = showFields(DELAY, {}, <ErrorHandling />);
  await userEvent.type(screen.getByLabelText("Attempts"), "25");
  expect(screen.getByText("A whole number from 1 to 20.")).toBeTruthy();
  await userEvent.type(screen.getByLabelText("Timeout (seconds)"), "0");
  expect(screen.getByText("A number of seconds above 0, up to 86,400.")).toBeTruthy();
  expect(step().options).toEqual({ max_attempts: 2 }); // "2", before the "5"
  expect(held().map((u) => [u.kind, u.text])).toEqual([["limit", "25"], ["limit", "0"]]);
});

it("keeps a limit a refused write turned away, with its reason", async () => {
  const { node: step, held, refuse } = showFields(DELAY, {}, <ErrorHandling />);
  refuse("Not written: the draft can't be changed now.");
  await userEvent.type(screen.getByLabelText("Attempts"), "4");
  expect(screen.getByLabelText<HTMLInputElement>("Attempts").value).toBe("4");
  expect(screen.getByText("Not written: the draft can't be changed now.")).toBeTruthy();
  expect(step()).not.toHaveProperty("options");
  expect(held().map((u) => [u.kind, u.text])).toEqual([["limit", "4"]]);
});

it("keeps focus at a limit after its Discard (the final review)", async () => {
  showFields(DELAY, {}, <ErrorHandling />);
  const attempts = () => screen.getByLabelText<HTMLInputElement>("Attempts");
  await userEvent.type(attempts(), "25"); // "25" held: past 20
  await userEvent.click(screen.getByRole("button", { name: "Discard the edit to Attempts" }));
  await vi.waitFor(() => expect(document.activeElement).toBe(attempts()));
});
