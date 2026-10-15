// SPDX-License-Identifier: Apache-2.0
// A step test's result in its Test tab (4d-1c; the simulation design §7.6; the TestResult board): where it is while it
// runs; once ended, what a simulation proves, its status and where its data came from, its attempt, revision and run,
// a failure's code and message, the port a branch took or what a step set, the values used ("seeded", sensitive ones
// redacted) and its output.
import type { ReactNode } from "react";
import { Button } from "../../../components/Button";
import { ENDED, type StepSummary } from "../../../lib/simulations";
import { StatusChip } from "./chips";
import { Failure } from "./Failure";
import { lineOf, runId } from "./lifecycle";
import { field, originTag } from "./results";
import { SimBanner } from "./SimBanner";
import { InlineTags } from "./SimTags";
import { Pairs, Section, UsedValues } from "./UsedValues";
import type { SimulationSession } from "./useSimulation";

const REDACTED = "[redacted]";
const something = (v: unknown) =>
  v !== undefined && v !== null && !(typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0);

/** What one instance of a step did, from its final attempt: a failure, the port a branch took or what a step set, and its
 * output (`used`, the values it was given, before it). Its status and origin are said beside it. */
export function InstanceDetail({ final, max, used }: { final: unknown; max: number | null; used?: ReactNode }) {
  const output = field(final, "output");
  const port = field(field(final, "effect"), "port");
  const assignments = field(field(final, "effect"), "assignments");
  return (
    <>
      <Failure final={final} max={max} />
      {typeof port === "string" && <p className="text-small">{`Takes → ${port}.`}</p>}
      {typeof assignments === "object" && assignments !== null && (
        <Section title="Sets">
          <Pairs pairs={Object.entries(assignments).map(([k, v]): [string, unknown] => [k, v === REDACTED ? v : JSON.stringify(v)])} />
        </Section>
      )}
      {used}
      {something(output) && (
        <Section title="Output">
          <pre className="overflow-x-auto rounded-md border border-line bg-surface-2 p-2 font-mono text-meta">{JSON.stringify(output, null, 2)}</pre>
        </Section>
      )}
    </>
  );
}

export function StepResult({ session, stepKey, attemptsOf }: {
  session: SimulationSession; stepKey: string; attemptsOf: (s: StepSummary) => number | null;
}) {  // prettier-ignore
  const { state, phase } = session;
  const s = session.steps?.steps[0] ?? null; // a step test's summary holds its target alone
  const ended = phase !== null && ENDED.has(phase);
  const line = lineOf(session);
  const final = s?.final;
  const max = s ? attemptsOf(s) : null;
  const attempt = field(final, "attempt");
  const facts = state
    ? [typeof attempt === "number" && max ? `attempt ${attempt} of ${max}` : null, `revision ${state.request.draft_revision}`, `run ${runId(state.request.id)}`]
    : [];  // prettier-ignore
  return (
    <Section title={`Result · ${stepKey}`}>
      {line && <p className="text-small">{line}</p>}
      {session.local.kind === "unknown" && (
        <div>
          <Button size="sm" onClick={() => void session.checkAgain()}>Check again</Button>
        </div>
      )}
      {ended && state && phase !== "refused" && phase !== "dead" && (
        <>
          <SimBanner>
            <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
          </SimBanner>
          <p className="flex flex-wrap items-center gap-2">
            <StatusChip phase={phase} />
            {s && <InlineTags tags={[originTag(s.origin)]} />}
            <span className="text-small text-muted">{facts.filter(Boolean).join(" · ")}</span>
          </p>
          <InstanceDetail final={final} max={max} used={<UsedValues state={state} />} />
        </>
      )}
    </Section>
  );
}
