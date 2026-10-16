// SPDX-License-Identifier: Apache-2.0
// The Runs page (editor 4e-1; the runs design §5.2; the Main and ListStates boards): a tenant's runs, newest first,
// each named by its id's first eight characters, a link to its page, with its workflow, its status (and a simulation
// said so), what started it, when, how long it ran and its error. A request that never started gives its reason's code
// and words. Below 640 px the rows become a list, each run's facts on its lines (§5.6; the Narrow boards). Its filters
// live in its address (§5.1); an empty list says what was asked, never that no run ever ran when the window hides them.
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Button } from "../../components/Button";
import { ModeChip, RunStatusChip } from "../../components/RunChips";
import { Table, Td, Th } from "../../components/Table";
import { When } from "../../components/When";
import { useNarrow } from "../../lib/media";
import { isEnded, runsQuery, searchOf, type RunFilters, type RunItem } from "../../lib/runs";
import { duration, reasonWords, runId } from "../../lib/runStatus";
import { useDocumentTitle } from "../../lib/title";
import { Filters } from "./Filters";
import { triggerOf } from "./trigger";

const WINDOW: Record<NonNullable<RunFilters["started"]>, string> = {
  "1h": "in the last hour",
  "24h": "in the last 24 hours",
  "7d": "in the last 7 days",
  "30d": "in the last 30 days",
  all: "",
};

/** When it started, else when it was queued. */
const startOf = (r: RunItem) => r.started_at ?? r.queued_at;
/** How long it ran, or has so far. */
const lasted = (r: RunItem) => duration(r.started_at, isEnded(r.status) ? r.ended_at : new Date(Date.now()).toISOString());

function RunLink({ tenantId, run }: { tenantId: string; run: RunItem }) {
  return (
    <Link to="/t/$tenantId/runs/$runId" params={{ tenantId, runId: run.id }} className="font-mono text-small font-medium text-accent-ink underline underline-offset-2">
      {runId(run.id)}
    </Link>
  );
}

function Status({ run }: { run: RunItem }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      <RunStatusChip status={run.status} />
      {run.mode === "simulate" && <ModeChip mode="simulate" draft={run.draft_snapshot_id !== null} />}
    </span>
  );
}

/** Its error's code and message; a request that never started, its reason's code and words, and that nothing ran. */
function Problem({ run }: { run: RunItem }) {
  const reason = run.status === "refused" || run.status === "dead" ? (run.request?.reason ?? null) : null;
  const code = run.error?.code ?? reason;
  if (!code) return null;
  const words = run.error ? run.error.message : `${reasonWords(reason) ?? ""} Nothing ran.`.trim();
  return (
    <>
      <span className="block font-mono text-meta text-danger">{code}</span>
      {words && <span className="block text-small text-muted">{words}</span>}
    </>
  );
}

function RunTable({ tenantId, runs }: { tenantId: string; runs: RunItem[] }) {
  return (
    <Table label="Runs">
      <thead>
        <tr>
          <Th>Run</Th><Th>Workflow</Th><Th>Status</Th><Th>Trigger</Th><Th>Started</Th><Th>Duration</Th><Th>Error</Th>
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const trigger = triggerOf(r);
          const start = startOf(r);
          return (
            <tr key={r.id}>
              <Td className="align-top whitespace-nowrap"><RunLink tenantId={tenantId} run={r} /></Td>
              <Td className="align-top">{r.workflow_name ?? "—"}</Td>
              <Td className="align-top"><Status run={r} /></Td>
              <Td className="align-top">
                {trigger.kind}
                {trigger.detail && <span className="block text-small text-muted">{trigger.detail}</span>}
              </Td>
              <Td className="align-top text-small whitespace-nowrap">{start ? <When iso={start} /> : "—"}</Td>
              <Td className="align-top font-mono text-small whitespace-nowrap">{lasted(r) ?? "—"}</Td>
              <Td className="align-top"><Problem run={r} /></Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function RunList({ tenantId, runs }: { tenantId: string; runs: RunItem[] }) {
  return (
    <ul aria-label="Runs" className="flex flex-col">
      {runs.map((r) => {
        const trigger = triggerOf(r);
        const start = startOf(r);
        const took = lasted(r);
        return (
          <li key={r.id} className="flex flex-col gap-0.5 border-t border-line py-2.5 first:border-t-0">
            <span className="flex flex-wrap items-center gap-2">
              <RunLink tenantId={tenantId} run={r} />
              <Status run={r} />
            </span>
            <span>{r.workflow_name ?? "—"}</span>
            <span className="text-small text-muted">
              {trigger.kind}
              {trigger.detail && <>, {trigger.detail}</>}
              {start && <> · <When iso={start} /></>}
              {took && ` · ${took}`}
            </span>
            <Problem run={r} />
          </li>
        );
      })}
    </ul>
  );
}

/** What an empty list says: no match for the filters set; none in the window; else none yet (the ListStates board). */
function Empty({ filters, onChange }: { filters: RunFilters; onChange: (next: RunFilters) => void }) {
  const started = filters.started ?? "24h";
  const within = WINDOW[started];
  if (Object.keys(searchOf({ ...filters, started: undefined })).length > 0) {
    return (
      <p className="flex flex-wrap items-center gap-3 text-body text-muted">
        {`No runs match these filters${within ? ` ${within}` : ""}.`}
        <Button size="sm" onClick={() => onChange({})}>Clear the filters</Button>
      </p>
    );
  }
  if (started !== "all") {
    return (
      <p className="flex flex-wrap items-center gap-3 text-body text-muted">
        {`No runs ${within}.`}
        <Button size="sm" onClick={() => onChange({ started: "all" })}>Show all kept</Button>
      </p>
    );
  }
  return <p className="text-body text-muted">No runs yet. A run starts by hand from a workflow, on a schedule, or from a webhook.</p>;
}

export function RunsPage({ tenantId, filters }: { tenantId: string; filters: RunFilters }) {
  useDocumentTitle("Runs");
  const navigate = useNavigate();
  const first = useQuery(runsQuery(tenantId, filters));
  const narrow = useNarrow();
  const runs = first.data ?? [];
  const setFilters = (next: RunFilters) => void navigate({ to: "/t/$tenantId/runs", params: { tenantId }, search: searchOf(next) });
  return (
    <section className="flex flex-col gap-4 p-6">
      <h1 className="text-h1 font-semibold">Runs</h1>
      <Filters tenantId={tenantId} filters={filters} onChange={setFilters} />
      {first.isPending ? (
        <p role="status" className="text-body text-muted">Reading the runs…</p>
      ) : first.isError ? (
        <p className="flex flex-wrap items-center gap-3">
          <span role="alert" className="text-body text-danger">The runs couldn&apos;t be read.</span>
          <Button size="sm" onClick={() => void first.refetch()}>Try again</Button>
        </p>
      ) : runs.length === 0 ? (
        <Empty filters={filters} onChange={setFilters} />
      ) : narrow ? (
        <RunList tenantId={tenantId} runs={runs} />
      ) : (
        <RunTable tenantId={tenantId} runs={runs} />
      )}
    </section>
  );
}
