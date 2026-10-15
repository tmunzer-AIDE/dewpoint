// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SimulationRequest, SimulationState, StepSummary } from "../../../lib/simulations";
import { SimulationPanel } from "./SimulationPanel";
import type { SimulationSession } from "./useSimulation";

const ID = "7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b";
const QUEUED_AT = "2026-10-15T10:42:05Z";
const request = (status: SimulationRequest["status"]): SimulationRequest => ({
  id: ID, workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null, mode: "simulate",
  source: "manual", status, reason: null, queued_at: QUEUED_AT, ended_at: null, admission_checks: [],
});  // prettier-ignore
const run = (status: NonNullable<SimulationState["run"]>["status"], ended_at: string | null = null): SimulationState["run"] => ({
  status, queued_at: QUEUED_AT, started_at: "2026-10-15T10:42:05Z", ended_at, error: null, iterations: 0,
});
const step = (key: string, statuses: Record<string, number>): StepSummary => ({
  step_id: `id-${key}`, key, type: "flow.transform@1", origin: "evaluated", instances: Object.values(statuses).reduce((a, b) => a + b, 0),
  statuses, ports: {}, final: null,
});  // prettier-ignore
const at = (iso: string) => new Date(iso).toLocaleTimeString("en-GB");

function session(over: Partial<SimulationSession> = {}): SimulationSession {
  return {
    local: { kind: "admitted", frozen: null, request: request("queued"), latest: false },
    state: null, steps: null, phase: null, busy: true, readFailed: false, asOf: null, cancelFailed: false,
    start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(() => Promise.resolve("requested" as const)), readAgain: vi.fn(),
    ...over,
  };  // prettier-ignore
}
const admitted = (status: SimulationRequest["status"], r: SimulationState["run"] = null, over: Partial<SimulationSession> = {}, cancel_requested = false) => {
  const state: SimulationState = { request: request(status), run: r, cancel_requested, read_back: "kept", input: {}, seeds: null };
  return session({ state, ...over });
};

function show(s: SimulationSession) {
  const onSimulateAgain = vi.fn();
  const onClose = vi.fn();
  render(<SimulationPanel session={s} onSimulateAgain={onSimulateAgain} onClose={onClose} />);
  return { onSimulateAgain, onClose };
}

describe("the Simulation panel's lifecycle (§7.2; the Lifecycle and Running boards)", () => {
  it("says it's being sent, and when its answer is lost, sends the same request again on Check again", async () => {
    const frozen = { key: "k1", revision: 14, body: { input: {} } };
    show(session({ local: { kind: "submitting", frozen } }));
    expect(screen.getByText("Sending the simulation…")).toBeTruthy();
    const lost = session({ local: { kind: "unknown", frozen } });
    show(lost);
    expect(screen.getByText(/It isn't known whether the simulation started: its answer was lost\. Checking sends the same request again: while the first request is still kept, it can't start a second time\./)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(lost.checkAgain).toHaveBeenCalled();
  });

  it("waits for a run slot, and can be cancelled", async () => {
    const s = admitted("queued", null, { phase: "queued" });
    show(s);
    expect(screen.getByRole("heading", { name: "Simulation" })).toBe(document.activeElement);
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(screen.getByText("Simulated")).toBeTruthy();
    expect(screen.getByText("Waiting for a free run slot.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Cancel the simulation" }));
    expect(s.cancel).toHaveBeenCalled();
  });

  it("says how far it got while it runs, and that it's read again while the tab is open", () => {
    const steps = { given: "input" as const, steps: [step("get_site", { succeeded: 1 }), step("list_aps", { succeeded: 1 }), step("has_aps", { running: 1 }), step("report", {})] };
    show(admitted("started", run("running"), { phase: "running", steps }));
    expect(screen.getByText("2 of 4 steps ended.")).toBeTruthy();
    expect(screen.getByText(`Started ${at("2026-10-15T10:42:05Z")} · draft revision 14 · run 7c1e9a40`)).toBeTruthy();
    expect(screen.getByText("Read again every few seconds while this tab is open.")).toBeTruthy();
  });

  it("says a cancel is requested until the server confirms it", () => {
    show(admitted("started", run("running"), { phase: "cancel_requested" }, true));
    expect(screen.getByText("Cancel requested. It's shown as cancelled once the server confirms it.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel requested" })).toHaveProperty("disabled", true);
  });

  it("says how it ended, and offers to simulate again", async () => {
    const steps = { given: "input" as const, steps: [step("get_site", { succeeded: 1 }), step("notify", { failed: 1 })] };
    const { onSimulateAgain } = show(admitted("started", run("failed", "2026-10-15T10:42:19Z"), { phase: "failed", steps, busy: false }));
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("Ended: failed at notify · 14 s · draft revision 14 · run 7c1e9a40")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "◌ Simulate again" }));
    expect(onSimulateAgain).toHaveBeenCalled();
  });

  it("says when it couldn't start", () => {
    show(admitted("dead", null, { phase: "dead", busy: false }));
    expect(screen.getByText("Couldn't start")).toBeTruthy();
    expect(screen.getByText("The simulation couldn't be started. Nothing ran.")).toBeTruthy();
  });

  it("keeps the last state it knew when a read fails, as of when it was read", async () => {
    const s = admitted("started", run("running"), { phase: "running", readFailed: true, asOf: Date.parse("2026-10-15T10:42:31Z") });
    show(s);
    expect(screen.getByText("Running")).toBeTruthy();
    expect(screen.getByText(`Couldn't be refreshed · as of ${at("2026-10-15T10:42:31Z")}.`)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Read it again" }));
    expect(s.readAgain).toHaveBeenCalled();
  });

  it("after a reload, is the person's latest simulation, labelled as exactly that", () => {
    const s = admitted("started", run("succeeded", "2026-10-15T10:42:19Z"), { phase: "succeeded", busy: false });
    s.local = { kind: "admitted", frozen: null, request: request("started"), latest: true };
    show(s);
    expect(screen.getByText(`Your latest simulation of this workflow, started ${at(QUEUED_AT)} on revision 14.`)).toBeTruthy();
  });

  it("says when a cancel didn't go through (the review's 3)", () => {
    show(admitted("started", run("running"), { phase: "running", cancelFailed: true }));
    expect(screen.getByText("Couldn't cancel it. Try again.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel the simulation" })).toBeTruthy();
  });

  it("closes on Close and on Escape", async () => {
    const { onClose } = show(admitted("queued", null, { phase: "queued" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
