// SPDX-License-Identifier: Apache-2.0
// A simulation's status and what it is, as chips (4d-1c; the Lifecycle and ResultPanel boards): words first, the
// colour only repeating them (§7.4). Simulated results are slate (D2), never live orange (D3).
import type { Phase } from "../../../lib/simulations";
import { STATUS } from "./lifecycle";

const TONE: Partial<Record<Phase, string>> = {
  succeeded: "border-ok text-ok",
  failed: "border-danger text-danger",
  deadline_exceeded: "border-danger text-danger",
  dead: "border-danger text-danger",
  refused: "border-danger text-danger",
};

export function StatusChip({ phase }: { phase: Phase }) {
  return <span className={`rounded-md border px-1.5 text-meta ${TONE[phase] ?? "border-line-strong text-muted"}`}>{STATUS[phase]}</span>;
}

export function SimulatedChip() {
  return <span className="rounded-md border border-sim px-1.5 text-meta text-sim">Simulated</span>;
}
