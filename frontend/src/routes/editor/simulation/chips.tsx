// SPDX-License-Identifier: Apache-2.0
// A simulation's status and what it is, as chips (4d-1c; the Lifecycle and ResultPanel boards): words first, the
// colour only repeating them (§7.4), in every run's vocabulary (4e-1). Simulated results are slate (D2), never live
// orange (D3).
import { ToneChip } from "../../../components/RunChips";
import { RUN_STATUS } from "../../../lib/runStatus";
import type { Phase } from "../../../lib/simulations";
import { STATUS } from "./lifecycle";

/** Its status, looking as every run's does (the runs design §5.5); a cancel asked for, as running. */
export function StatusChip({ phase }: { phase: Phase }) {
  return <ToneChip tone={phase === "cancel_requested" ? "running" : RUN_STATUS[phase].tone}>{STATUS[phase]}</ToneChip>;
}

export function SimulatedChip() {
  return <span className="rounded-md border border-sim px-1.5 text-meta text-sim">Simulated</span>;
}
