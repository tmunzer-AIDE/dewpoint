// SPDX-License-Identifier: Apache-2.0
// The Simulation panel (4d-1c; the simulation design §7.2, §7.5; the Lifecycle, Running and ResultPanel boards): where
// the editor's simulation is, from being sent to its end, in words. It opens when a simulation is sent, and from the
// toolbar's strip and the canvas's bar; one side panel at a time, as the others (side.ts). The result's sections (the
// banner, the checks on the server, the steps, the input used) come in below the lifecycle as `children`.
import { Fragment, useEffect, useRef, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { duration, runId } from "../../../lib/runStatus";
import { ENDED } from "../../../lib/simulations";
import { SIDE } from "../side";
import { SimulatedChip, StatusChip } from "./chips";
import { clock, endedWhat, lineOf } from "./lifecycle";
import type { SimulationSession } from "./useSimulation";

/** `runOf`: its run's name as a link to the run's page (the runs design §5.1), where there's a router to follow it. */
export function SimulationPanel({ session, onSimulateAgain, onClose, runOf, children }: {
  session: SimulationSession; onSimulateAgain?: () => void; onClose: () => void; runOf?: (id: string) => ReactNode; children?: ReactNode;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const { local, state, phase } = session;
  const steps = session.steps?.steps ?? [];
  const ended = phase !== null && ENDED.has(phase);
  const request = state?.request ?? (local.kind === "admitted" ? local.request : null);
  const run = state?.run ?? null;
  const said = (iso: string | null) => (iso ? clock(iso) : "a moment ago");

  const line = lineOf(session); // where it is, in a sentence

  // Which run it is, and when it started or how it ended (§7.5).
  const named = request && (runOf ? runOf(request.id) : `run ${runId(request.id)}`);
  const facts: ReactNode[] | null =
    request && state && phase && phase !== "dead" && phase !== "refused"
      ? ended
        ? [`Ended: ${endedWhat(phase, steps)}`, duration(run?.started_at ?? null, run?.ended_at ?? null), `draft revision ${request.draft_revision}`, named]
        : [`Started ${said(run?.started_at ?? request.queued_at)}`, `draft revision ${request.draft_revision}`, named]
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
      {facts && (
        <p className="text-small text-muted">
          {facts.filter(Boolean).map((f, i) => (
            <Fragment key={i}>
              {i > 0 && " · "}
              {f}
            </Fragment>
          ))}
        </p>
      )}
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
      {session.cancelFailed && !ended && <p className="text-small text-danger">Couldn&apos;t cancel it. Try again.</p>}
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
