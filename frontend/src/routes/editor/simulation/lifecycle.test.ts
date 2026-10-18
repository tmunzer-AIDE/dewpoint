// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { StepSummary } from "../../../lib/simulations";
import { STATUS, endedWhat, stepsEnded } from "./lifecycle";

const step = (key: string, statuses: Record<string, number>, origin: StepSummary["origin"] = "evaluated"): StepSummary => ({
  step_id: `id-${key}`, key, type: "flow.transform@1", origin, instances: Object.values(statuses).reduce((a, b) => a + b, 0),
  statuses, ports: {}, final: null,
});  // prettier-ignore

describe("a simulation's lifecycle, in words (§7.2, §7.5; the Lifecycle board)", () => {
  it("words a simulation's status as every run's, keeping \"Not simulated\" for its own refusals (the runs design §5.5)", () => {
    expect(STATUS.deadline_exceeded).toBe("Ran out of time");
    expect(STATUS.dead).toBe("Couldn't start");
    expect(STATUS.refused).toBe("Not simulated");
    expect(STATUS.cancel_requested).toBe("Running");
  });

  it("counts the steps that have ended while it runs", () => {
    const steps = [step("a", { succeeded: 1 }), step("b", { running: 1 }), step("c", {}, "not_reached_yet"), step("d", { failed: 2, skipped: 1 })];
    expect(stepsEnded(steps)).toEqual({ ended: 2, of: 4 });
  });

  it("says how it ended, naming the step that decided it", () => {
    const steps = [step("get_site", { succeeded: 1 }), step("list_aps", { succeeded: 1 }), step("notify", { failed: 1 }), step("report", { cancelled: 1 })];
    expect(endedWhat("succeeded", steps)).toBe("succeeded");
    expect(endedWhat("failed", steps)).toBe("failed at notify");
    expect(endedWhat("failed", [])).toBe("failed");
    expect(endedWhat("cancelled", steps)).toBe("cancelled after notify");
    expect(endedWhat("cancelled", [])).toBe("cancelled before any step ran");
    expect(endedWhat("deadline_exceeded", steps)).toBe("the run passed its deadline, during report");
    expect(endedWhat("deadline_exceeded", [])).toBe("the run passed its deadline");
  });
});
