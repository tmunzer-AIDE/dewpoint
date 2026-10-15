// SPDX-License-Identifier: Apache-2.0
// A simulation's lifecycle in words (4d-1c; the simulation design §7.2, §7.5; the Lifecycle, Running and ResultPanel
// boards): its status, how long it ran, which run it is, how far it got, and how it ended, naming the step that
// decided it, from the server's per-step summary in run order.
import type { Phase, StepSummary } from "../../../lib/simulations";
import type { SimulationSession } from "./useSimulation";

export const STATUS: Record<Phase, string> = {
  queued: "Queued",
  starting: "Starting",
  running: "Running",
  cancel_requested: "Running", // still going: it's cancelled once the server says so
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  deadline_exceeded: "Deadline exceeded",
  refused: "Not simulated",
  dead: "Couldn't start",
};

/** How long a run ran, as a person reads it: "14 s", "3 min 20 s", "1 h 2 min"; null when either end is unknown. */
export function duration(from: string | null, to: string | null): string | null {
  if (from === null || to === null) return null;
  const s = Math.round((Date.parse(to) - Date.parse(from)) / 1000);
  if (s < 1) return "under 1 s";
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
  return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ""}`;
}

/** A run named by its id's first eight characters (a run's id is its request's). */
export const runId = (id: string) => id.slice(0, 8);

/** The time of day an instant was, to the second, as the person's clock says it. */
export const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB");

/** How many of the steps have ended while it runs: those with an instance, none of them still running. */
export function stepsEnded(steps: StepSummary[]): { ended: number; of: number } {
  return { ended: steps.filter((s) => s.instances > 0 && !s.statuses.running).length, of: steps.length };
}

const did = (s: StepSummary, ...statuses: string[]) => statuses.some((k) => (s.statuses[k] ?? 0) > 0);

/** How a simulation ended, naming the step that decided it (the Lifecycle board): the first that failed, the last that
 * ran before a cancel, the one the deadline stopped. */
export function endedWhat(phase: Phase, steps: StepSummary[]): string {
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
