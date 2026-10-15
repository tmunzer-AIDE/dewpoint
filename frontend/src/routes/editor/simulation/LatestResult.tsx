// SPDX-License-Identifier: Apache-2.0
// A step in the person's latest simulation of the whole workflow, in its Test tab (4d-1c; the simulation design §7.6:
// "After a workflow simulation, the step's result in it, with an iteration picker"; the TestTab and TestOther boards):
// its tags, as on the canvas; one instance shown as it is; a step that ran in a loop, one iteration at a time, picked
// from the first page of its instances, or the one the Simulation panel's "Open" asked for.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button } from "../../../components/Button";
import { Select } from "../../../components/Field";
import { sameId } from "../../../lib/graph";
import { ENDED, stepInstancesQuery, type StepSummary } from "../../../lib/simulations";
import type { GraphNode } from "../../../lib/workflows";
import { clock } from "./lifecycle";
import { field, tagsOf } from "./results";
import { InstanceDetail } from "./StepResult";
import { Section } from "./UsedValues";
import type { SimulationSession } from "./useSimulation";

const PAGE = 50;

/** An iteration as a person counts it: from 1, nested ones joined ("2/3"). */
const counted = (key: string) => key.split("/").map((part) => Number(part.split(":").at(-1)) + 1).join("/");
const keyOf = (item: unknown) => {
  const key = field(item, "iteration_key");
  return typeof key === "string" ? key : "";
};
function optionOf(item: unknown): string {
  const status = field(item, "status");
  const code = field(field(item, "error"), "code");
  return `${counted(keyOf(item))} · ${typeof status === "string" ? status.replace("_", " ") : "not recorded"}${typeof code === "string" ? ` · ${code}` : ""}`;
}

export function LatestResult({ tenantId, workflowId, session, node, attemptsOf, iteration }: {
  tenantId: string; workflowId: string; session: SimulationSession; node: GraphNode;
  attemptsOf: (s: StepSummary) => number | null; iteration: { key: string; n: number } | null;
}) {  // prettier-ignore
  const { state, phase } = session;
  const s = state && state.request.target_step_id === null ? session.steps?.steps.find((x) => sameId(x.step_id, node.id)) : undefined;
  const ended = phase !== null && ENDED.has(phase);
  const several = s !== undefined && s.instances > 1;
  const page = useQuery({
    ...stepInstancesQuery(tenantId, workflowId, state?.request.id ?? "", node.id, { offset: 0, limit: PAGE }),
    enabled: several && ended,
  });
  const [picked, setPicked] = useState<string | null>(iteration?.key ?? null);
  const [shown, setShown] = useState<string | null>(iteration?.key ?? null);
  useEffect(() => {
    if (iteration) {
      setPicked(iteration.key);
      setShown(iteration.key);
    }
  }, [iteration?.n]);
  // The iteration "Open" asked for, read on its own when it's past the picker's first page (§7.5: a loop's iterations).
  const first = page.data?.items ?? [];
  const askedPast = iteration !== null && page.data !== undefined && !first.some((i) => keyOf(i) === iteration.key);
  const asked = useQuery({
    ...stepInstancesQuery(tenantId, workflowId, state?.request.id ?? "", node.id, { offset: 0, limit: 1, within: iteration?.key }),
    enabled: several && ended && askedPast,
  });
  if (!s || !state) return null;
  const items = askedPast && asked.data ? [...first, ...asked.data.items.filter((i) => keyOf(i) === iteration?.key)] : first;
  const choice = picked ?? (items[0] ? keyOf(items[0]) : "");
  const item = shown === null ? undefined : items.find((i) => keyOf(i) === shown);
  const words = tagsOf(s, { maxAttempts: attemptsOf(s), ended }).map((t) => t.text).join(" · ");
  return (
    <Section title="In your latest simulation">
      <p className="text-small">{`Revision ${state.request.draft_revision}, ${state.request.queued_at ? clock(state.request.queued_at) : "earlier"}: ${words}.`}</p>
      {s.instances === 1 && <InstanceDetail final={s.final} max={attemptsOf(s)} />}
      {several && ended && (
        page.isError ? (
          <p className="text-small text-muted">Its iterations couldn&apos;t be read.</p>
        ) : !page.data ? (
          <p className="text-small text-muted">Reading its iterations…</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-0 grow">
                <Select label="Iteration" value={choice} onChange={(e) => setPicked(e.target.value)}>
                  {items.map((i) => <option key={keyOf(i)} value={keyOf(i)}>{optionOf(i)}</option>)}
                </Select>
              </div>
              <Button size="md" onClick={() => setShown(choice || null)}>Show</Button>
            </div>
            {page.data.total > first.length && <p className="text-small text-muted">{`The first ${first.length} of ${page.data.total} iterations.`}</p>}
            {item !== undefined && <InstanceDetail final={item} max={attemptsOf(s)} />}
          </>
        )
      )}
    </Section>
  );
}
