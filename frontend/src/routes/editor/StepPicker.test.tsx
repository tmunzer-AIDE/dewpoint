// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { StepPicker } from "./StepPicker";

const t = (ref: string, kind: "control" | "action", ports: string[], extra = {}) => ({
  ref, type: ref.split("@")[0], version: 1, kind, state: "active", title: ref.split("@")[0]!.split(".").pop(), description: `does ${ref}`,
  ports, dynamic_ports: null, config_schema: {}, output_schema: {}, side_effect: "none", credentials: [], capabilities: [],
  retry: { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] }, timeout_s: 60, ...extra,
}) as never;  // prettier-ignore
const TYPES = [
  t("flow.transform@1", "control", ["out"]),
  t("flow.if@1", "control", ["true", "false"]),
  t("flow.old@1", "control", ["out"], { state: "deprecated" }),
  t("testkit.http_call@1", "action", ["out"], { side_effect: "idempotent", credentials: ["testkit"] }),
];
const EDGE = { from: { node: "a", port: "out" }, to: { node: "b" } };

it("offers every active type after a port, in Flow and Actions, with what an action changes and needs", async () => {
  const onPick = vi.fn();
  render(<StepPicker mode={{ kind: "after", from: { node: "a", port: "out" } }} types={TYPES} onPick={onPick} onConnect={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: /flow\.old@1/ })).toBeNull(); // deprecated: new versions shouldn't use it
  const call = screen.getByRole("option", { name: /testkit\.http_call@1/ });
  expect(call.textContent).toContain("Changes things; safe to repeat");
  expect(call.textContent).toContain("Uses a testkit connection");
  await userEvent.click(screen.getByRole("option", { name: /flow\.if@1/ }));
  expect(onPick).toHaveBeenCalledWith(TYPES[1]);
});

it("offers only steps that continue the flow mid-edge, and says why", () => {
  render(<StepPicker mode={{ kind: "insert", edge: EDGE }} types={TYPES} onPick={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByRole("option", { name: /flow\.if@1/ })).toBeNull();
  expect(screen.getByRole("option", { name: /flow\.transform@1/ })).toBeTruthy();
  expect(screen.getByText("Only steps that continue the flow can go here.")).toBeTruthy();
});

it("offers to connect an existing step instead, after a port", async () => {
  const onConnect = vi.fn();
  render(<StepPicker mode={{ kind: "after", from: { node: "a", port: "out" } }} types={TYPES} onPick={vi.fn()} onConnect={onConnect} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("option", { name: "Connect to an existing step…" }));
  expect(onConnect).toHaveBeenCalled();
});
