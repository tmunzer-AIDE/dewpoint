// SPDX-License-Identifier: Apache-2.0
// What a simulation was given, as its request stored it (4d-1c; the simulation design §6.6's read-back, §7.5, §7.6; the
// ResultPanel and TestResult boards): a workflow's input, or a step test's values, each "seeded"; sensitive values
// redacted by the server, never recomputed from today's draft.
import { useId, type ReactNode } from "react";
import { Tag } from "../../../components/Tag";
import type { SimulationState } from "../../../lib/simulations";

const REDACTED = "[redacted]"; // the server's marker for a sensitive value (engine/runtime/projection.py)

/** A stored value as a person reads it: redacted in words, text as it is, the rest as JSON. */
export const shown = (v: unknown): string => (v === REDACTED ? "redacted" : typeof v === "string" ? v : JSON.stringify(v));

/** A titled section of the result. */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-1.5">
      <h3 id={id} className="text-small font-semibold">{title}</h3>
      {children}
    </section>
  );
}

/** Pairs, a name and its value: a dl. */
export function Pairs({ pairs, tag }: { pairs: [string, unknown][]; tag?: string }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-small">
      {pairs.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="font-mono break-all text-muted">{k}</dt>
          <dd className="break-words">
            {shown(v)}
            {tag && <> <Tag>{tag}</Tag></>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function UsedValues({ state }: { state: SimulationState }) {
  const seeds = state.request.target_step_id !== null;
  const what = seeds ? "values used" : "input used";
  const values = (seeds ? state.seeds : state.input) ?? {};
  return (
    <Section title={seeds ? "Values used" : "Input used"}>
      {state.read_back === "absent" ? (
        <p className="text-small text-muted">{seeds ? "The values used aren't kept any more." : "The input used isn't kept any more."}</p>
      ) : state.read_back === "unreadable" ? (
        <p className="text-small text-muted">{`The ${what} couldn't be read back.`}</p>
      ) : (
        <>
          <p className="text-small text-muted">
            {seeds ? "As this step test's request stored them, sensitive values redacted." : "As this simulation's request stored it, sensitive values redacted."}
          </p>
          <Pairs pairs={Object.entries(values)} tag={seeds ? "seeded" : undefined} />
        </>
      )}
    </Section>
  );
}
