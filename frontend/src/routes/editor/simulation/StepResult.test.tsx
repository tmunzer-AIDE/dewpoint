// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SimulationRequest, SimulationState, StepSummary } from "../../../lib/simulations";
import { StepResult } from "./StepResult";
import type { SimulationSession } from "./useSimulation";

const ID = "7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b";
const request = (over: Partial<SimulationRequest> = {}): SimulationRequest => ({
  id: ID, workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: "id-notify", mode: "simulate",
  source: "manual", status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [], ...over,
});  // prettier-ignore
const summary = (over: Partial<StepSummary> = {}): StepSummary => ({
  step_id: "id-notify", key: "notify", type: "slack.post@1", origin: "fixture_not_sent", instances: 1, statuses: { succeeded: 1 }, ports: {},
  final: { attempt: 1, status: "succeeded", output: { ok: true, channel: "C0FIXTURE" }, effect: null }, ...over,
});  // prettier-ignore

function session(phase: SimulationSession["phase"], s: StepSummary | null, state: Partial<SimulationState> = {}): SimulationSession {
  const full: SimulationState = {
    request: request(), run: { status: "succeeded", queued_at: null, started_at: "2026-10-15T10:42:05Z", ended_at: "2026-10-15T10:42:06Z", error: null, iterations: 0 },
    cancel_requested: false, read_back: "kept", input: null, seeds: { "/steps/get_site/output/name": "HQ Paris", "/trigger/api_token": "[redacted]" }, ...state,
  };  // prettier-ignore
  return {
    local: { kind: "admitted", frozen: null, request: full.request, latest: false }, state: full, steps: s ? { given: "seeded", steps: [s] } : null,
    phase, busy: false, readFailed: false, asOf: null, start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(), readAgain: vi.fn(),
  };  // prettier-ignore
}
const show = (s: SimulationSession) => render(<StepResult session={s} stepKey="notify" attemptsOf={() => 3} />);

describe("a step test's result in its Test tab (§7.6; the TestResult board)", () => {
  it("says what it proves, its status and origin, its attempt, revision and run", () => {
    show(session("succeeded", summary()));
    const result = screen.getByRole("region", { name: "Result · notify" });
    expect(within(result).getByText("Simulated.").parentElement?.textContent).toBe("Simulated. Nothing was sent. Results don't prove the live call will succeed.");
    expect(within(result).getByText("Succeeded")).toBeTruthy();
    expect(within(result).getByText("fixture · not sent")).toBeTruthy();
    expect(within(result).getByText("attempt 1 of 3 · revision 14 · run 7c1e9a40")).toBeTruthy();
  });

  it("shows the values used, each seeded, sensitive ones redacted, and the output", () => {
    show(session("succeeded", summary()));
    const used = screen.getByRole("region", { name: "Values used" });
    const pairs = within(used).getAllByRole("term").map((t) => `${t.textContent}=${t.nextElementSibling?.textContent}`);
    expect(pairs).toEqual(["/steps/get_site/output/name=HQ Paris seeded", "/trigger/api_token=redacted seeded"]);
    expect(screen.getByRole("region", { name: "Output" }).querySelector("pre")?.textContent).toBe('{\n  "ok": true,\n  "channel": "C0FIXTURE"\n}');
  });

  it("says the port a branch took, and what a step set", () => {
    show(session("succeeded", summary({ type: "flow.if@1", origin: "evaluated", final: { attempt: 1, status: "succeeded", output: {}, effect: { port: "true" } } })));
    expect(screen.getByText("Takes → true.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Output" })).toBeNull(); // nothing besides the port
  });

  it("lists what a step set, sensitive values redacted", () => {
    const set = { attempt: 1, status: "succeeded", output: {}, effect: { assignments: { channel: "#ops-alerts", webhook_key: "[redacted]" } } };
    show(session("succeeded", summary({ type: "flow.set_variables@1", origin: "evaluated", final: set })));
    const sets = screen.getByRole("region", { name: "Sets" });
    expect(within(sets).getAllByRole("term").map((t) => `${t.textContent}=${t.nextElementSibling?.textContent}`)).toEqual(['channel="#ops-alerts"', "webhook_key=redacted"]);
  });

  it("says a failure's code and message, its attempts, and that nothing was sent", () => {
    const failed = { attempt: 3, status: "failed", output: null, error: { code: "invalid_blocks", message: "Block 2 has no text." } };
    show(session("failed", summary({ statuses: { failed: 1 }, final: failed })));
    expect(screen.getByText("invalid_blocks").parentElement?.textContent).toBe("invalid_blocks Block 2 has no text. 3 attempts, the configured retries. Nothing was sent.");
  });

  it("says where it is while it runs", () => {
    show(session("queued", null, { run: null }));
    expect(within(screen.getByRole("region", { name: "Result · notify" })).getByText("Waiting for a free run slot.")).toBeTruthy();
  });
});
