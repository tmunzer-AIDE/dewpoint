// SPDX-License-Identifier: Apache-2.0
// A run's status and what it was, as chips (editor 4e-1; the runs design §5.5; the Main and RunFailed boards): words
// first, the look only repeating them. Live is orange (D3); a simulation is slate with the hatch (D2), which sits only
// behind slate text (`text-sim`), at 4.5:1 over it.
import type { ReactNode } from "react";
import { RUN_STATUS, type RunStatus, type Tone } from "../lib/runStatus";

const TONE: Record<Tone, string> = {
  waiting: "border-dashed border-line-control text-muted",
  running: "border-accent text-accent-ink",
  ok: "border-ok text-ok",
  danger: "border-danger text-danger",
  neutral: "border-line-strong text-muted",
};

export function ToneChip({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`rounded-md border px-1.5 text-meta whitespace-nowrap ${TONE[tone]}`}>{children}</span>;
}

export function RunStatusChip({ status }: { status: RunStatus }) {
  return <ToneChip tone={RUN_STATUS[status].tone}>{RUN_STATUS[status].word}</ToneChip>;
}

/** Live, or a simulation of a published version, or of a draft. */
export function ModeChip({ mode, draft }: { mode: "live" | "simulate"; draft: boolean }) {
  if (mode === "live") return <span className="rounded-md border border-live bg-live-bg px-1.5 text-meta whitespace-nowrap text-live">Live</span>;
  return (
    <span className="hatch-sim rounded-md border border-sim bg-sim-bg px-1.5 text-meta whitespace-nowrap text-sim">
      {draft ? "Draft simulation" : "Simulated"}
    </span>
  );
}
