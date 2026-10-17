// SPDX-License-Identifier: Apache-2.0
// A step's result in a run, its drawer's Result tab (editor 4e-1; the runs design §5.3; the RunFailed and RunLoop
// boards). An instance: its status, "attempt N of M" and its times; its error's code and message; its attempts, one row
// each (at most 20, §4.4); the last attempt's input and its output, sensitive values redacted and long ones cut as the
// server stored them, said in words (D20: never dots); and the run it started. Its attempts are read again while the
// run runs. A step with no instance says why, in the canvas's words.
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Fragment, useId, type ReactNode } from "react";
import { ToneChip } from "../../components/RunChips";
import { runAttemptsQuery, runQuery, type RunStep, type RunStepSummary } from "../../lib/runs";
import { RUN_STATUS, STEP_STATUS, runId, took } from "../../lib/runStatus";
import { timeOf } from "../../lib/when";
import { Chip, PreviewValue } from "../editor/drawer/PillDetails";
import { ORIGIN } from "../editor/simulation/results";

const READ_EVERY = 5000; // an open drawer's reads, while the run runs: with the summary
const at = (iso: string) => timeOf(Date.parse(iso));
const MARKS: Record<string, string> = { "[redacted]": "redacted", "[truncated]": "truncated" };

export function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-1.5">
      <h3 id={id} className="text-small font-semibold">{title}</h3>
      {children}
    </section>
  );
}

/** A preview as the server stored it: an object as its keys and values, a value wholly redacted or cut as its mark. */
function Values({ value, none }: { value: unknown; none: string }) {
  const one = (v: unknown) => (typeof v === "string" && MARKS[v] ? <Chip>{MARKS[v]}</Chip> : <PreviewValue value={v} />);
  if (value === null || value === undefined) return <p className="text-small text-muted">{none}</p>;
  if (typeof value !== "object" || Array.isArray(value)) return <p className="text-small break-words">{one(value)}</p>;
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return <p className="text-small text-muted">{none}</p>;
  return (
    <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-small">
      {entries.map(([k, v]) => (
        <Fragment key={k}>
          <dt className="font-mono break-all">{k}</dt>
          <dd className="min-w-0 break-words">{one(v)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** The run a step started: its name, a link to its page, its workflow and its status. */
function SubRun({ tenantId, id }: { tenantId: string; id: string }) {
  const child = useQuery(runQuery(tenantId, id));
  return (
    <p className="text-small">
      {"Its run: "}
      <Link to="/t/$tenantId/runs/$runId" params={{ tenantId, runId: id }} className="font-mono text-accent-ink underline underline-offset-2">
        {runId(id)}
      </Link>
      {child.data && ` · ${child.data.workflow_name ?? "—"} · ${RUN_STATUS[child.data.status].word}`}
    </p>
  );
}

/** One instance of a step, from its final attempt: as its attempts' read gives it once read, fresher while the run
 * runs; `max`: its attempts, its own or its type's. */
export function InstanceResult({ tenantId, runId: id, step: final, max, ended }: {
  tenantId: string; runId: string; step: RunStep; max: number | null; ended: boolean;
}) {  // prettier-ignore
  const attempts = useQuery({ ...runAttemptsQuery(tenantId, id, final.step_id, final.iteration_key), refetchInterval: ended ? false : READ_EVERY });
  const all = attempts.data?.items.length ? attempts.data.items : [final];
  const step = all.at(-1)!;
  const from = all[0]?.started_at ?? step.started_at;
  const to = step.ended_at;
  const times = from && to ? (at(from) === at(to) ? at(from) : `${at(from)} to ${at(to)}`) : from ? `since ${at(from)}` : null;
  const facts = [max ? `attempt ${step.attempt} of ${max}` : `attempt ${step.attempt}`, times, took(from, to)].filter(Boolean).join(" · ");
  const status = STEP_STATUS[step.status];
  return (
    <>
      <p className="flex flex-wrap items-center gap-2">
        <ToneChip tone={status.tone}>{status.word}</ToneChip>
        <span className="text-small text-muted">{facts}</span>
      </p>
      {step.error && (
        <p className="rounded-lg border border-danger bg-danger-bg px-3 py-2 text-small">
          <span className="font-mono text-danger">{step.error.code}</span>
          {step.error.message && ` · ${step.error.message}`}
        </p>
      )}
      <Section title="Attempts">
        {attempts.isError ? (
          <p className="text-small text-muted">Its attempts couldn&apos;t be read.</p>
        ) : (
          <ol className="flex flex-col text-small">
            {all.map((a) => (
              <li key={a.attempt} className="grid grid-cols-[1.5rem_auto_minmax(0,1fr)_auto_auto] items-center gap-2 border-t border-line py-1.5 first:border-t-0">
                <span>{a.attempt}</span>
                <ToneChip tone={STEP_STATUS[a.status].tone}>{STEP_STATUS[a.status].word.toLowerCase()}</ToneChip>
                <span className="truncate font-mono text-meta">{a.error?.code ?? ""}</span>
                <span className="text-muted">{a.started_at ? at(a.started_at) : ""}</span>
                <span className="text-muted">{took(a.started_at, a.ended_at) ?? ""}</span>
              </li>
            ))}
          </ol>
        )}
      </Section>
      <Section title="Input">
        <p className="text-small text-muted">As the last attempt received it. Sensitive values are redacted and long ones cut.</p>
        <Values value={step.input} none="None." />
      </Section>
      <Section title="Output">
        {step.status === "failed" ? <p className="text-small text-muted">None: the step failed.</p> : <Values value={step.output} none="None." />}
      </Section>
      {step.child_run_id && <SubRun tenantId={tenantId} id={step.child_run_id} />}
    </>
  );
}

/** A step's result: its one instance, or why it has none; `summary` undefined when the run's steps don't name it. */
export function StepResult({ tenantId, runId: id, summary, max, ended, several }: {
  tenantId: string; runId: string; summary: RunStepSummary | undefined; max: number | null; ended: boolean; several: ReactNode;
}) {  // prettier-ignore
  if (!summary) return <p className="text-small text-muted">This run has no result for this step.</p>;
  if (summary.instances === 0) {
    const why = summary.origin === null ? "No result." : `${ORIGIN[summary.origin].charAt(0).toUpperCase()}${ORIGIN[summary.origin].slice(1)}.`;
    return <p className="text-small">{why}</p>;
  }
  if (summary.instances === 1 && summary.final) return <InstanceResult tenantId={tenantId} runId={id} step={summary.final} max={max} ended={ended} />;
  return several;
}
