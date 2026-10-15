// SPDX-License-Identifier: Apache-2.0
// A simulation's result in the Simulation panel (4d-1c; the simulation design §7.5; the ResultPanel and Running
// boards), below its lifecycle: what a simulation proves (the banner), the checks the server found when it admitted
// it, the steps in run order with the canvas's tags and Go to, a loop's iterations paged, and the input used, as the
// request stored it (§6.6's read-back: never recomputed from today's draft).
import { useId, useState, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { findNode } from "../../../lib/graph";
import { ENDED, type StepSummary } from "../../../lib/simulations";
import type { GraphDoc } from "../../../lib/workflows";
import { bodyOf } from "./loopBody";
import { Iterations } from "./Iterations";
import { tagsOf } from "./results";
import { SimBanner } from "./SimBanner";
import { InlineTags } from "./SimTags";
import type { SimulationSession } from "./useSimulation";

const REDACTED = "[redacted]"; // the server's marker for a sensitive value (engine/runtime/projection.py)

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-1.5">
      <h3 id={id} className="text-small font-semibold">{title}</h3>
      {children}
    </section>
  );
}

const shown = (v: unknown): string => (v === REDACTED ? "redacted" : typeof v === "string" ? v : JSON.stringify(v));
const iterationKey = (final: StepSummary["final"]): string => {
  const key = final?.iteration_key;
  return typeof key === "string" ? key : "";
};

export function SimulationResult({ tenantId, workflowId, session, doc, attemptsOf, onGoTo, onOpen }: {
  tenantId: string; workflowId: string; session: SimulationSession; doc: GraphDoc;
  attemptsOf: (s: StepSummary) => number | null; onGoTo: (stepId: string) => void;
  onOpen?: (stepId: string, iterationKey: string) => void;
}) {  // prettier-ignore
  const [open, setOpen] = useState<string | null>(null); // the loop whose iterations are shown
  const { state, phase } = session;
  if (!state || !phase) return null;
  const ended = ENDED.has(phase);
  const ran = phase !== "refused" && phase !== "dead";
  const request = state.request;
  const all = session.steps?.steps ?? [];
  const steps = ended ? all : all.filter((s) => s.instances > 0);
  const goTo = (id: string, key: string) =>
    findNode(doc, id) ? <Button size="sm" aria-label={`Go to ${key}`} onClick={() => onGoTo(id)}>Go to</Button> : null;

  return (
    <>
      {ended && ran && (
        <SimBanner>
          <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
          {all.some((s) => s.origin === "evaluated_not_waited") && (
            <p>Flow delays and wait-until weren&apos;t waited; the simulation clock wasn&apos;t advanced.</p>
          )}
        </SimBanner>
      )}
      {request.admission_checks.length > 0 && (
        <Section title="Checks on the server">
          <p className="text-small text-muted">Found when the simulation was admitted. They didn&apos;t stop it; a live run would meet them.</p>
          <ul className="flex flex-col text-small">
            {request.admission_checks.map((d, i) => {
              const key = d.node ? findNode(doc, d.node)?.key : undefined;
              return (
                <li key={i} className="flex flex-wrap items-center gap-2 border-t border-line py-1.5 first:border-t-0">
                  <span className="grow">{d.message}</span>
                  {d.fix && <span className="basis-full text-muted">{d.fix}</span>}
                  {d.node && key !== undefined && goTo(d.node, key)}
                </li>
              );
            })}
          </ul>
        </Section>
      )}
      {ran && steps.length > 0 && (
        <Section title={ended ? "Steps, in run order" : "Steps so far"}>
          <ul className="flex flex-col text-small">
            {steps.map((s) => {
              const loop = s.type.startsWith("flow.loop@") && s.instances === 1 && findNode(doc, s.step_id) !== undefined;
              const body = loop && ended ? bodyOf(doc, s.step_id) : [];
              const expanded = open === s.step_id && body.length > 0;
              return (
                <li key={s.step_id} className="flex flex-wrap items-center gap-1.5 border-t border-line py-1.5 first:border-t-0">
                  <span data-key className="font-mono">{s.key}</span>
                  <InlineTags tags={tagsOf(s, { maxAttempts: attemptsOf(s), ended })} />
                  <span className="grow" />
                  {body.length > 0 && (
                    <Button size="sm" aria-label={`Iterations of ${s.key}`} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : s.step_id)}>
                      Iterations
                    </Button>
                  )}
                  {goTo(s.step_id, s.key)}
                  {expanded && (
                    <div className="basis-full ps-3">
                      <Iterations
                        tenantId={tenantId} workflowId={workflowId} requestId={request.id} loop={{ key: s.key, prefix: iterationKey(s.final) }}
                        body={body.map((n) => ({ id: n.id, key: n.key, type: n.type }))} onOpen={onOpen}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </Section>
      )}
      {request.target_step_id === null && (
        <Section title="Input used">
          {state.read_back === "absent" ? (
            <p className="text-small text-muted">The input used isn&apos;t kept any more.</p>
          ) : state.read_back === "unreadable" ? (
            <p className="text-small text-muted">The input used couldn&apos;t be read back.</p>
          ) : (
            <>
              <p className="text-small text-muted">As this simulation&apos;s request stored it, sensitive values redacted.</p>
              <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-small">
                {Object.entries(state.input ?? {}).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-mono text-muted">{k}</dt>
                    <dd className="break-words">{shown(v)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </Section>
      )}
    </>
  );
}
