// SPDX-License-Identifier: Apache-2.0
// A step in the person's latest simulation of the whole workflow, in its Test tab (4d-1c; the simulation design §7.6:
// "After a workflow simulation, the step's result in it, with an iteration picker"; the TestTab and TestOther boards):
// its tags, as on the canvas; one instance shown as it is; a step that ran in a loop, one iteration at a time, picked
// from the first page of its instances, or the one the Simulation panel's "Open" asked for.
import { useQueryClient } from "@tanstack/react-query";
import { sameId } from "../../../lib/graph";
import { ENDED, stepInstancesQuery, type StepSummary } from "../../../lib/simulations";
import type { GraphNode } from "../../../lib/workflows";
import { clock } from "./lifecycle";
import { IterationPicker } from "./IterationPicker";
import type { InstancePages } from "./loopBody";
import { tagsOf } from "./results";
import { InstanceDetail } from "./StepResult";
import { Section } from "./UsedValues";
import type { SimulationSession } from "./useSimulation";

export function LatestResult({ tenantId, workflowId, session, node, attemptsOf, iteration }: {
  tenantId: string; workflowId: string; session: SimulationSession; node: GraphNode;
  attemptsOf: (s: StepSummary) => number | null; iteration: { key: string; n: number } | null;
}) {  // prettier-ignore
  const { state, phase } = session;
  const qc = useQueryClient();
  const s = state && state.request.target_step_id === null ? session.steps?.steps.find((x) => sameId(x.step_id, node.id)) : undefined;
  const ended = phase !== null && ENDED.has(phase);
  if (!s || !state) return null;
  const several = s.instances > 1;
  const requestId = state.request.id;
  const pages: InstancePages = {
    key: ["simulation", tenantId, workflowId, requestId],
    read: (stepId, page) => qc.query(stepInstancesQuery(tenantId, workflowId, requestId, stepId, page)),
  };
  const words = tagsOf(s, { maxAttempts: attemptsOf(s), ended }).map((t) => t.text).join(" · ");
  return (
    <Section title="In your latest simulation">
      <p className="text-small">{`Revision ${state.request.draft_revision}, ${state.request.queued_at ? clock(state.request.queued_at) : "earlier"}: ${words}.`}</p>
      {s.instances === 1 && <InstanceDetail final={s.final} max={attemptsOf(s)} />}
      {several && ended && (
        <IterationPicker pages={pages} stepId={node.id} iteration={iteration} show={(item) => <InstanceDetail final={item} max={attemptsOf(s)} />} />
      )}
    </Section>
  );
}
