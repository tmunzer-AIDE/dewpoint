// SPDX-License-Identifier: Apache-2.0
// The canvas's bar for the editor's simulation (4d-1c; the simulation design §7.3; the Running and ResultCanvas
// boards). While it runs: that nothing is sent, and Cancel. Once ended: the hatched banner (nothing was sent, and what
// that doesn't prove; that flow timers weren't waited, when one wasn't), its status, revision and end, the panel, and
// "Hide the result". Hidden: one bar that brings it back; the simulation, its history, and one running are untouched.
import { Button } from "../../../components/Button";
import { ENDED, type Phase } from "../../../lib/simulations";
import { StatusChip } from "./chips";
import { STATUS, clock } from "./lifecycle";
import { SimBanner } from "./SimBanner";

const BAR = "flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small";

export function ResultBar({ phase, revision, endedAt, notWaited, hidden, onHide, onShow, onPanel, onCancel }: {
  phase: Phase; revision: number; endedAt: string | null; notWaited: boolean; hidden: boolean;
  onHide: () => void; onShow: () => void; onPanel: () => void; onCancel: () => void;
}) {  // prettier-ignore
  if (!ENDED.has(phase)) {
    const going = phase === "cancel_requested" ? "cancel requested" : phase;
    return (
      <div className={BAR}>
        <span className="grow text-sim">{`◌ Simulating · ${going} · nothing is sent`}</span>
        {phase !== "cancel_requested" && <Button size="sm" onClick={onCancel}>Cancel</Button>}
      </div>
    );
  }
  if (hidden) {
    return (
      <div className={BAR}>
        <span className="grow">{`Simulation result hidden · ${STATUS[phase]} · revision ${revision}`}</span>
        <Button size="sm" onClick={onShow}>Show the result</Button>
      </div>
    );
  }
  return (
    <div className="border-b border-line bg-surface px-5 py-2.5">
      <SimBanner role="status">
        <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
        {notWaited && <p>Flow delays and wait-until weren&apos;t waited; the simulation clock wasn&apos;t advanced.</p>}
        <p className="flex flex-wrap items-center gap-2 text-ink">
          <StatusChip phase={phase} />
          <span className="grow text-muted">{`revision ${revision}${endedAt ? ` · ${clock(endedAt)}` : ""}`}</span>
          <Button size="sm" onClick={onPanel}>Simulation</Button>
          <Button size="sm" onClick={onHide}>Hide the result</Button>
        </p>
      </SimBanner>
    </div>
  );
}
