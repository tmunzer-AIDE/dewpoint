// SPDX-License-Identifier: Apache-2.0
// The Runs page (editor 4e-1; the runs design §5.2; the Main and ListStates boards): a tenant's runs, newest first,
// each named by its id's first eight characters, a link to its page, with its workflow, its status (and a simulation
// said so), what started it, when, how long it ran and its error. A request that never started gives its reason's code
// and words. Below 640 px the rows become a list, each run's facts on its lines (§5.6; the Narrow boards). Its filters
// live in its address (§5.1); an empty list says what was asked, never that no run ever ran when the window hides them.
// The first page is read again every 5 s while the page is visible; older pages, loaded on, aren't; each run is listed
// once (`listed`). A refresh that fails keeps the list and says since when; a change is said once, through the shell's
// live region (§5.6).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Button } from "../../components/Button";
import { ModeChip, RunStatusChip } from "../../components/RunChips";
import { Table, Td, Th } from "../../components/Table";
import { When } from "../../components/When";
import { announce } from "../../lib/announce";
import { useNarrow } from "../../lib/media";
import { PAGE, cursorOf, isEnded, listed, runsQuery, searchOf, type RunFilters, type RunItem } from "../../lib/runs";
import { duration, reasonWords, runId } from "../../lib/runStatus";
import { useDocumentTitle } from "../../lib/title";
import { timeOf } from "../../lib/when";
import { Filters } from "./Filters";
import { triggerOf } from "./trigger";

const WINDOW: Record<NonNullable<RunFilters["started"]>, string> = {
  "1h": "in the last hour",
  "24h": "in the last 24 hours",
  "7d": "in the last 7 days",
  "30d": "in the last 30 days",
  all: "",
};

const EVERY = 5000; // the first page is read again this often (§5.2)

/** Every run read so far, the latest read of each: the first page's reads and the older pages'. */
const remember = (seen: Map<string, RunItem>, runs: RunItem[]) => new Map([...seen, ...runs.map((r): [string, RunItem] => [r.id, r])]);

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
  const qc = useQueryClient();
  const first = useQuery({ ...runsQuery(tenantId, filters), refetchInterval: EVERY });
  const narrow = useNarrow();
  // What was read under these filters: begun again when they change (React's "adjusting state when a prop changes").
  const asked = JSON.stringify(searchOf(filters));
  const [read, setRead] = useState({ asked, seen: new Map<string, RunItem>(), older: "idle" as "idle" | "reading" | "failed" | "end" });
  if (read.asked !== asked) setRead({ asked, seen: new Map(), older: "idle" });
  useEffect(() => {
    if (first.data) setRead((r) => ({ ...r, seen: remember(r.seen, first.data) }));
  }, [first.data]);
  // A change is said once: an answer equal to the last keeps its reference (structural sharing), so says nothing.
  const said = useRef(first.data);
  useEffect(() => {
    if (said.current !== undefined && first.data !== said.current) announce("Updated");
    said.current = first.data;
  }, [first.data]);
  useEffect(() => {
    if (first.isRefetchError) announce("The runs couldn't be refreshed.");
  }, [first.isRefetchError]);
  const runs = first.data ? listed(first.data, [...read.seen.values()]) : [];
  const cursor = cursorOf(runs);
  const more = first.data?.length === PAGE && read.older !== "end" && cursor !== null;
  async function loadMore() {
    if (cursor === null || read.older === "reading") return; // one page at a time

    setRead((r) => ({ ...r, older: "reading" }));
    try {
      const page = await qc.query(runsQuery(tenantId, filters, cursor)); // read once: an older page isn't read again
      setRead((r) => (r.asked === asked ? { ...r, seen: remember(r.seen, page), older: page.length < PAGE ? "end" : "idle" } : r));
    } catch {
      setRead((r) => (r.asked === asked ? { ...r, older: "failed" } : r));
    }
  }
  const setFilters = (next: RunFilters) => void navigate({ to: "/t/$tenantId/runs", params: { tenantId }, search: searchOf(next) });
  const started = filters.started ?? "24h";
  return (
    <section className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-h1 font-semibold">Runs</h1>
        {first.isRefetchError ? (
          <p className="flex flex-wrap items-center gap-2 text-small text-muted">
            {`Couldn't be refreshed · as of ${timeOf(first.dataUpdatedAt)}`}
            <Button size="sm" onClick={() => void first.refetch()}>Try again</Button>
          </p>
        ) : (
          <p className="text-small text-muted">Updates every 5 s</p>
        )}
      </div>
      <Filters tenantId={tenantId} filters={filters} onChange={setFilters} />
      {first.isPending ? (
        <p role="status" className="text-body text-muted">Reading the runs…</p>
      ) : first.isLoadingError ? (
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
      {read.older === "end" ? (
        <p className="text-small text-muted">{started === "all" ? "No older runs are kept." : `No older runs ${WINDOW[started]}.`}</p>
      ) : (
        more && (
          <div className="flex flex-wrap items-center gap-3">
            {/* Never disabled while it reads: a disabled button drops the keyboard's focus to the page. */}
            <Button size="md" aria-disabled={read.older === "reading" || undefined} onClick={() => void loadMore()}>Load more</Button>
            <span className="text-small text-muted">
              {read.older === "reading"
                ? "Reading older runs…"
                : read.older === "failed"
                  ? "Older runs couldn't be read. Try again."
                  : "The 50 most recent first. New runs appear at the top as they're found."}
            </span>
          </div>
        )
      )}
    </section>
  );
}
