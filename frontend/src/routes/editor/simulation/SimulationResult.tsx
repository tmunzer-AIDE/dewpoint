// SPDX-License-Identifier: Apache-2.0
// A simulation's result in the Simulation panel (4d-1c; the simulation design §7.5; the ResultPanel and Running
// boards), below its lifecycle: what a simulation proves (the banner), the checks the server found when it admitted
// it, the steps in run order with the canvas's tags and Go to, a loop's iterations paged, and the input used, as the
// request stored it (§6.6's read-back: never recomputed from today's draft). A result from before the person's edits
// says so, and marks each step changed since or no longer in the draft; a failed step says its code and message, and
// that nothing was sent; a refusal is shown in the server's words (§7.7; the Stale and Refusals boards).
import { useState } from "react";
import { Button } from "../../../components/Button";
import { findNode, idKey } from "../../../lib/graph";
import { ENDED, type StepSummary } from "../../../lib/simulations";
import type { GraphDoc } from "../../../lib/workflows";
import { Failure } from "./Failure";
import { bodyOf } from "./loopBody";
import { Iterations } from "./Iterations";
import { tagsOf } from "./results";
import { SimBanner } from "./SimBanner";
import { Refusal } from "./Refusal";
import { InlineTags } from "./SimTags";
import { STALE, staleWords, type Changes, type Stale } from "./stale";
import { Section, UsedValues } from "./UsedValues";
import type { SimulationSession } from "./useSimulation";

const iterationKey = (final: StepSummary["final"]): string => {
  const key = final?.iteration_key;
  return typeof key === "string" ? key : "";
};

export function SimulationResult({ tenantId, workflowId, session, doc, ran, stale, changes, attemptsOf, onGoTo, onShowProblems, onOpen }: {
  tenantId: string; workflowId: string; session: SimulationSession;
  doc: GraphDoc; ran: GraphDoc | null; // the draft as it is; the draft it ran (its snapshot), once read
  stale: Stale | null; changes: Changes | null; attemptsOf: (s: StepSummary) => number | null;
  onGoTo: (stepId: string) => void; onShowProblems: () => void; onOpen?: (stepId: string, iterationKey: string) => void;
}) {  // prettier-ignore
  const [open, setOpen] = useState<string | null>(null); // the loop whose iterations are shown
  const { local, state, phase } = session;
  if (local.kind === "refused") {
    return <Refusal error={local.error} doc={doc} onGoTo={onGoTo} onShowProblems={onShowProblems} onTryAgain={() => void session.checkAgain()} />;
  }
  if (!state || !phase) return null;
  const ended = ENDED.has(phase);
  const began = phase !== "refused" && phase !== "dead"; // it ran, if only in part
  const request = state.request;
  const all = session.steps?.steps ?? [];
  const steps = ended ? all : all.filter((s) => s.instances > 0);
  const goTo = (id: string, key: string) =>
    findNode(doc, id) ? <Button size="sm" aria-label={`Go to ${key}`} onClick={() => onGoTo(id)}>Go to</Button> : null;

  const graph = ran ?? doc;
  const target = request.target_step_id; // a step test's step
  const targetKey = target ? (findNode(doc, target)?.key ?? all[0]?.key ?? "the step") : null;
  return (
    <>
      {ended && stale && (
        <p className={STALE}>
          <strong>Before your edits:</strong> {staleWords(stale, true)}
        </p>
      )}
      {ended && began && (
        <SimBanner>
          {targetKey ? (
            <p><strong>{`Step test: ${targetKey}.`}</strong> Only this step ran. Nothing was sent.</p>
          ) : (
            <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
          )}
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
      {began && steps.length > 0 && (
        <Section title={ended ? "Steps, in run order" : "Steps so far"}>
          <ul className="flex flex-col text-small">
            {steps.map((s) => {
              const loop = s.type.startsWith("flow.loop@") && s.instances === 1 && findNode(graph, s.step_id) !== undefined;
              const body = loop && ended ? bodyOf(graph, s.step_id) : [];
              const expanded = open === s.step_id && body.length > 0;
              return (
                <li key={s.step_id} className="flex flex-wrap items-center gap-1.5 border-t border-line py-1.5 first:border-t-0">
                  <span data-key className="font-mono">{s.key}</span>
                  <InlineTags tags={tagsOf(s, { maxAttempts: attemptsOf(s), ended })} />
                  {!findNode(doc, s.step_id) && <span className="text-meta text-muted">no longer in the draft</span>}
                  {changes?.changed.has(idKey(s.step_id)) && <span className="text-meta text-muted">changed since</span>}
                  <span className="grow" />
                  {body.length > 0 && (
                    <Button size="sm" aria-label={`Iterations of ${s.key}`} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : s.step_id)}>
                      Iterations
                    </Button>
                  )}
                  {goTo(s.step_id, s.key)}
                  {s.instances === 1 && <Failure final={s.final} max={attemptsOf(s)} />}
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
      <UsedValues state={state} />
    </>
  );
}
