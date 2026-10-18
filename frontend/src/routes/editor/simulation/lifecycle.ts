// SPDX-License-Identifier: Apache-2.0
// A simulation's lifecycle in words (4d-1c; the simulation design §7.2, §7.5; the Lifecycle, Running and ResultPanel
// boards): its status, how long it ran, which run it is, how far it got, and how it ended, naming the step that
// decided it, from the server's per-step summary in run order.
import { RUN_STATUS } from "../../../lib/runStatus";
import type { Phase, StepSummary } from "../../../lib/simulations";
import type { SimulationSession } from "./useSimulation";

/** Every run's words (the runs design §5.5), but a simulation the server refused, which is "Not simulated", and one
 * whose cancel is asked, still running until the server says it's cancelled. */
export const STATUS: Record<Phase, string> = {
  ...(Object.fromEntries(Object.entries(RUN_STATUS).map(([status, s]) => [status, s.word])) as Record<keyof typeof RUN_STATUS, string>),
  cancel_requested: "Running",
  refused: "Not simulated",
};

/** The time of day an instant was, to the second, as the person's clock says it. */
export const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB");

/** How many of the steps have ended while it runs: those with an instance, none of them still running. */
export function stepsEnded(steps: StepSummary[]): { ended: number; of: number } {
  return { ended: steps.filter((s) => s.instances > 0 && !s.statuses.running).length, of: steps.length };
}

const did = (s: Pick<StepSummary, "statuses">, ...statuses: string[]) => statuses.some((k) => (s.statuses[k] ?? 0) > 0);

/** How a simulation ended, naming the step that decided it (the Lifecycle board): the first that failed, the last that
 * ran before a cancel, the one the deadline stopped. */
export function endedWhat(phase: Phase, steps: Pick<StepSummary, "key" | "statuses">[]): string {
  if (phase === "failed") {
    const at = steps.find((s) => did(s, "failed"));
    return at ? `failed at ${at.key}` : "failed";
  }
  if (phase === "cancelled") {
    const after = steps.findLast((s) => did(s, "succeeded", "failed"));
    return after ? `cancelled after ${after.key}` : "cancelled before any step ran";
  }
  if (phase === "deadline_exceeded") {
    const during = steps.findLast((s) => did(s, "cancelled", "running"));
    return during ? `the run passed its deadline, during ${during.key}` : "the run passed its deadline";
  }
  return STATUS[phase].toLowerCase();
}

const LOST =
  "It isn't known whether the simulation started: its answer was lost. Checking sends the same request again: while the " +
  "first request is still kept, it can't start a second time.";

/** Where a simulation is, in a sentence (§7.2; the Lifecycle and Running boards); null once its status says it all. */
export function lineOf(session: SimulationSession): string | null {
  const { local, state, phase } = session;
  if (local.kind === "submitting") return "Sending the simulation…";
  if (local.kind === "unknown") return LOST;
  if (local.kind === "admitted" && state === null) return "Reading the simulation…";
  if (phase === "queued") return "Waiting for a free run slot.";
  if (phase === "starting") return "Its run is being started.";
  if (phase === "running") {
    const { ended, of } = stepsEnded(session.steps?.steps ?? []);
    return session.steps ? `${ended} of ${of} steps ended.` : "Running.";
  }
  if (phase === "cancel_requested") return "Cancel requested. It's shown as cancelled once the server confirms it.";
  if (phase === "dead") return "The simulation couldn't be started. Nothing ran.";
  if (phase === "refused") return state?.request.reason ?? "The simulation was refused.";
  return null;
}
