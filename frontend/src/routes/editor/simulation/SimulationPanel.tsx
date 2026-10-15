// SPDX-License-Identifier: Apache-2.0
// The Simulation panel (4d-1c; the simulation design §7.2, §7.5; the Lifecycle, Running and ResultPanel boards): where
// the editor's simulation is, from being sent to its end, in words. It opens when a simulation is sent, and from the
// toolbar's strip and the canvas's bar; one side panel at a time, as the others (side.ts). The result's sections (the
// banner, the checks on the server, the steps, the input used) come in below the lifecycle as `children`.
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { ENDED } from "../../../lib/simulations";
import { SIDE } from "../side";
import { SimulatedChip, StatusChip } from "./chips";
import { clock, duration, endedWhat, runId, stepsEnded } from "./lifecycle";
import type { SimulationSession } from "./useSimulation";

const LOST =
  "It isn't known whether the simulation started: its answer was lost. Checking sends the same request again: while the " +
  "first request is still kept, it can't start a second time.";

export function SimulationPanel({ session, onSimulateAgain, onClose, children }: {
  session: SimulationSession; onSimulateAgain?: () => void; onClose: () => void; children?: ReactNode;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const { local, state, phase } = session;
  const steps = session.steps?.steps ?? [];
  const ended = phase !== null && ENDED.has(phase);
  const request = state?.request ?? (local.kind === "admitted" ? local.request : null);
  const run = state?.run ?? null;
  const said = (iso: string | null) => (iso ? clock(iso) : "a moment ago");

  let line: string | null = null; // where it is, in a sentence
  if (local.kind === "submitting") line = "Sending the simulation…";
  else if (local.kind === "unknown") line = LOST;
  else if (local.kind === "admitted" && state === null) line = "Reading the simulation…";
  else if (phase === "queued") line = "Waiting for a free run slot.";
  else if (phase === "starting") line = "Its run is being started.";
  else if (phase === "running") {
    const { ended: done, of } = stepsEnded(steps);
    line = session.steps ? `${done} of ${of} steps ended.` : "Running.";
  } else if (phase === "cancel_requested") line = "Cancel requested. It's shown as cancelled once the server confirms it.";
  else if (phase === "dead") line = "The simulation couldn't be started. Nothing ran.";
  else if (phase === "refused") line = request?.reason ?? "The simulation was refused.";

  // Which run it is, and when it started or how it ended (§7.5).
  const facts =
    request && state && phase && phase !== "dead" && phase !== "refused"
      ? ended
        ? [`Ended: ${endedWhat(phase, steps)}`, duration(run?.started_at ?? null, run?.ended_at ?? null), `draft revision ${request.draft_revision}`, `run ${runId(request.id)}`]
        : [`Started ${said(run?.started_at ?? request.queued_at)}`, `draft revision ${request.draft_revision}`, `run ${runId(request.id)}`]
      : null;  // prettier-ignore

  return (
    <aside
      aria-labelledby="simulation-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className={`${SIDE} gap-4`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="simulation-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Simulation</h2>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {phase && (
        <p className="flex flex-wrap items-center gap-2">
          <StatusChip phase={phase} />
          <SimulatedChip />
        </p>
      )}
      {facts && <p className="text-small text-muted">{facts.filter(Boolean).join(" · ")}</p>}
      {line && <p className="text-small">{line}</p>}
      {local.kind === "admitted" && local.latest && request && (
        <p className="text-small text-muted">
          {`Your latest simulation of this workflow, started ${said(request.queued_at)} on revision ${request.draft_revision}.`}
        </p>
      )}
      {session.readFailed && (
        <p className="flex flex-wrap items-center gap-2 text-small">
          {`Couldn't be refreshed · as of ${session.asOf ? clock(new Date(session.asOf).toISOString()) : "earlier"}.`}
          <Button size="sm" onClick={session.readAgain}>Read it again</Button>
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {local.kind === "unknown" && <Button size="sm" onClick={() => void session.checkAgain()}>Check again</Button>}
        {(phase === "queued" || phase === "starting" || phase === "running") && (
          <Button size="sm" onClick={() => void session.cancel()}>Cancel the simulation</Button>
        )}
        {phase === "cancel_requested" && <Button size="sm" disabled>Cancel requested</Button>}
      </div>
      {children}
      {phase !== null && !ended && <p className="text-small text-muted">Read again every few seconds while this tab is open.</p>}
      {ended && onSimulateAgain && (
        <div>
          <Button variant="simulate" size="md" onClick={onSimulateAgain}>◌ Simulate again</Button>
        </div>
      )}
    </aside>
  );
}
