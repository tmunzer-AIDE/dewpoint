// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { StepSummary } from "../../../lib/simulations";
import { duration, endedWhat, runId, stepsEnded } from "./lifecycle";

const step = (key: string, statuses: Record<string, number>, origin: StepSummary["origin"] = "evaluated"): StepSummary => ({
  step_id: `id-${key}`, key, type: "flow.transform@1", origin, instances: Object.values(statuses).reduce((a, b) => a + b, 0),
  statuses, ports: {}, final: null,
});  // prettier-ignore

describe("a simulation's lifecycle, in words (§7.2, §7.5; the Lifecycle board)", () => {
  it("gives a run's duration as a person reads it", () => {
    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:19Z")).toBe("14 s");
    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:45:25Z")).toBe("3 min 20 s");
    expect(duration("2026-10-15T10:00:00Z", "2026-10-15T11:02:00Z")).toBe("1 h 2 min");
    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:05.300Z")).toBe("under 1 s");
    expect(duration(null, "2026-10-15T10:42:05Z")).toBeNull();
  });

  it("names a run by its id's first eight characters", () => {
    expect(runId("7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b")).toBe("7c1e9a40");
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
