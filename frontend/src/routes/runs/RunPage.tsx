// SPDX-License-Identifier: Apache-2.0
// A run's page (editor 4e-1; the runs design §5.3, §5.4; the RunFailed, RunRunning and RunOther boards), laid out like
// the editor (the owner's answer 6): the compact rail, the run's bar, its banner, and the graph it ran on the read-only
// canvas, each step's result beside its card, walked with the editor's keys (D16). It's read while it runs
// (useRunReads). A step's result opens in the editor's drawer, read only, its Result tab first; a failed run opens on
// its failed step (the owner's answer 6), and Close gives focus back to its card. A run past its tenant's retention, or
// an id that never was, is said to be neither, with Back to Runs; a run read while its tenant is erased says why it
// can't be (§5.5). Cancel, for the roles that hold run.cancel, while it waits or runs (useCancel).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
import { Button, LINK_BUTTON } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { When } from "../../components/When";
import { ApiError } from "../../lib/client";
import { START, findNode, idKey, nodesOf, portsOf, sameId } from "../../lib/graph";
import { canCancel, isEnded, runInstancesQuery, type Run, type RunStepSummary } from "../../lib/runs";
import { reasonWords, runId } from "../../lib/runStatus";
import { draftSnapshotQuery } from "../../lib/simulations";
import { useDocumentTitle } from "../../lib/title";
import { versionQuery } from "../../lib/triggers";
import { timeOf } from "../../lib/when";
import { nodeTypesQuery, tenantQuery, type GraphDoc } from "../../lib/workflows";
import { Canvas } from "../editor/Canvas";
import { NAV_KEYS, type NavKey } from "../editor/canvasNav";
import { READ_ONLY_ACTIONS } from "../editor/drawer/context";
import { StepDrawer } from "../editor/drawer/StepDrawer";
import { item, type ItemAction } from "../editor/items";
import { endedWhat } from "../editor/simulation/lifecycle";
import { bodyOf, type InstancePages } from "../editor/simulation/loopBody";
import { tagsOf, type SimTag } from "../editor/simulation/results";
import { useCanvasNav } from "../editor/useCanvasNav";
import { RunBanner, RunBar } from "./RunBar";
import { LoopResult, SeveralResult, StepResult } from "./RunResult";
import { StartDrawer } from "./StartDrawer";
import { triggerOf, triggerWords } from "./trigger";
import { useCancel } from "./useCancel";
import { useRunReads } from "./useRunReads";

/** Why a run couldn't be read: gone, the tenant's key gone during an erasure, or the read failed. */
function Unread({ tenantId, id, error, retry }: { tenantId: string; id: string; error: Error; retry: () => void }) {
  if (error instanceof ApiError && error.status === 404) {
    return (
      <section className="flex flex-col items-start gap-3 p-6">
        <h1 className="text-h1 font-semibold">
          Run <span className="font-mono">{runId(id)}</span>
        </h1>
        <p className="text-body">This run isn&apos;t kept any more, or it never existed here.</p>
        <Link to="/t/$tenantId/runs" params={{ tenantId }} className={LINK_BUTTON}>Back to Runs</Link>
      </section>
    );
  }
  if (error instanceof ApiError && error.code === "key_unusable") {
    return <p role="alert" className="p-6 text-body text-danger">This run can&apos;t be read while the tenant is being erased.</p>;
  }
  return (
    <p className="flex flex-wrap items-center gap-3 p-6">
      <span role="alert" className="text-body text-danger">The run couldn&apos;t be read.</span>
      <Button size="sm" onClick={retry}>Try again</Button>
    </p>
  );
}

/** What a request that never started says in place of a run's banner (§5.4): waiting, cancelled before it started, or
 * why it couldn't start or was refused, by its code and words. Nothing ran. */
function Unstarted({ run }: { run: Run }) {
  if (run.status === "refused" || run.status === "dead") {
    const code = run.request?.reason ?? null;
    const words = reasonWords(code);
    return (
      <p className="rounded-lg border border-danger bg-danger-bg px-3 py-2 text-small">
        {code && <span className="font-mono text-danger">{code}</span>}
        {`${code ? " · " : ""}${words ? `${words} ` : ""}Nothing ran.`}
      </p>
    );
  }
  const waiting = run.status === "queued" || run.status === "starting";
  return (
    <p className="text-small">
      {waiting ? "Waiting to start" : "Cancelled before it started"}
      {run.queued_at && <> · queued <When iso={run.queued_at} /></>}
      {waiting ? ". Nothing has run yet." : ". Nothing ran."}
    </p>
  );
}

const NONE: GraphDoc = { graph_format: 1, nodes: [], edges: [] };
const NO_STEPS: ReadonlySet<string> = new Set();
const NO_PROBLEMS = new Map();
const nothing = () => undefined;

export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: string }) {
  useDocumentTitle(`Run ${runId(id)}`);
  const { run, steps } = useRunReads(tenantId, id);
  const r = run.data;
  const types = useQuery(nodeTypesQuery);
  const tenant = useQuery(tenantQuery(tenantId));
  const cancel = useCancel(tenantId, id, r?.mode === "live");
  // The graph it ran: its version's, or the draft a draft simulation froze for it. Neither ever changes.
  const version = useQuery({ ...versionQuery(tenantId, r?.workflow_id ?? "", r?.version_id ?? ""), enabled: !!r?.version_id });
  const snapshot = useQuery({ ...draftSnapshotQuery(tenantId, r?.workflow_id ?? "", r?.draft_snapshot_id ?? ""), enabled: !!r?.draft_snapshot_id });
  const graph = (r?.draft_snapshot_id ? snapshot.data?.graph : version.data?.graph) ?? null;
  const typeMap = useMemo(() => new Map((types.data ?? []).map((t) => [t.ref, t])), [types.data]);
  const portsByStep = useCallback((nodeId: string) => {
    const n = graph && findNode(graph, nodeId);
    return n ? portsOf(n, typeMap.get(n.type)) : [];
  }, [graph, typeMap]);  // prettier-ignore
  const keys = useCanvasNav(graph ?? NONE, portsByStep, false);
  const ended = r !== undefined && isEnded(r.status);
  // An attempt is said "of" the step's own limit, else its type's.
  const attemptsOf = useCallback(
    (s: RunStepSummary) => (graph && findNode(graph, s.step_id)?.options?.max_attempts) ?? typeMap.get(s.type)?.retry.max_attempts ?? null,
    [graph, typeMap],
  );
  const tagsFor = useCallback(
    (s: RunStepSummary) => tagsOf(s, { maxAttempts: attemptsOf(s), ended, run: { action: typeMap.get(s.type)?.kind === "action" } }),
    [attemptsOf, ended, typeMap],
  );
  // Each step's tags, 4d-1c's grammar with a run's (§5.3): an action's time, a failure's code.
  const results = useMemo(() => new Map((steps.data?.steps ?? []).map((s): [string, SimTag[]] => [idKey(s.step_id), tagsFor(s)])), [steps.data, tagsFor]);
  // The step whose result is open. Undecided until its steps and graph are read: a failed run opens on its failed step.
  // A loop's "Open" asks for one iteration of a step in it (counted: the same one asked again shows again).
  const [open, setOpen] = useState<string | null | undefined>(undefined);
  const [iteration, setIteration] = useState<{ key: string; n: number } | null>(null);
  const qc = useQueryClient();
  const pages = useMemo<InstancePages>(
    () => ({ key: ["run", tenantId, id], read: (stepId, page) => qc.query(runInstancesQuery(tenantId, id, stepId, page)) }),
    [qc, tenantId, id],
  );
  if (open === undefined && r && steps.data && graph) {
    setOpen(r.status === "failed" ? (steps.data.steps.find((s) => (s.statuses.failed ?? 0) > 0)?.step_id ?? null) : null);
  }
  // Only a run never read says why it isn't shown: a read that fails later keeps what was read, and says so.
  if (!r) return run.isError ? <Unread tenantId={tenantId} id={id} error={run.error} retry={() => void run.refetch()} /> : <p role="status" className="p-6 text-body text-muted">Reading the run…</p>;
  const trigger = triggerOf(r);
  const given = steps.data?.given === "input" ? [{ text: "input", kind: "given" as const }] : undefined;
  function onCanvasKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!(e.target as HTMLElement).dataset.item || e.altKey || e.ctrlKey || e.metaKey || !NAV_KEYS.includes(e.key)) return;
    e.preventDefault();
    keys.walk(e.key as NavKey);
  }
  const endedAt = ended && r.ended_at && r.status !== "refused" && r.status !== "dead" ? r.ended_at : null;
  const node = open && graph ? findNode(graph, open) : undefined;
  const summary = node && steps.data?.steps.find((s) => idKey(s.step_id) === idKey(node.id));
  const onItem = (action: ItemAction) => {
    if (action.kind !== "open") return;
    setOpen(action.node);
    setIteration(null);
  };
  const openIteration = (stepId: string, key: string) => {
    setOpen(stepId);
    setIteration((i) => ({ key, n: (i?.n ?? 0) + 1 }));
  };
  // A request that never started shows its graph without tags: nothing ran (§5.4).
  const unstarted = r.request !== null && r.request.status !== "started";
  // A step's result: a loop that ran once, its iterations; a step in a loop, its instances one at a time; else its one
  // instance, or why it has none.
  function resultOf(summary: RunStepSummary | undefined) {
    const max = summary ? attemptsOf(summary) : null;
    if (summary && graph && summary.type.startsWith("flow.loop@") && summary.instances === 1 && summary.final) {
      const body = bodyOf(graph, summary.step_id).map((n) => ({ id: n.id, key: n.key, type: n.type }));
      return <LoopResult summary={summary} pages={pages} body={body} onOpen={openIteration} />;
    }
    if (summary && graph && summary.instances > 1) {
      const loop = nodesOf(graph).find((n) => n.type.startsWith("flow.loop@") && bodyOf(graph, n.id).some((b) => sameId(b.id, summary.step_id)));
      return (
        <SeveralResult
          tenantId={tenantId} runId={id} summary={summary} total={tagsFor(summary)[0]?.text ?? ""} pages={pages}
          loopKey={loop?.key ?? null} iteration={iteration} max={max} ended={ended}
        />
      );  // prettier-ignore
    }
    return <StepResult tenantId={tenantId} runId={id} summary={summary} max={max} ended={ended} />;
  }
  return (
    <div className="@container flex min-h-0 flex-1 flex-col">
      <RunBar tenantId={tenantId} run={r} version={version.data?.number ?? null}>
        {canCancel(tenant.data?.role) && !ended && !r.cancel_requested_at && (
          <Button size="sm" variant="danger-outline" disabled={cancel.state === "sending"} onClick={cancel.ask}>Cancel the run</Button>
        )}
      </RunBar>
      <div className="flex flex-col gap-2 border-b border-line bg-surface px-5 py-2.5">
        {run.isRefetchError && (
          <p className="flex flex-wrap items-center gap-2 text-small text-muted">
            {`Couldn't be refreshed · as of ${timeOf(run.dataUpdatedAt)}`}
            <Button size="sm" onClick={() => void run.refetch()}>Try again</Button>
          </p>
        )}
        {unstarted ? <Unstarted run={r} /> : <RunBanner run={r} />}
        {!unstarted && !r.outcomes_recorded && (
          <p className="text-small">This run is older than step-by-step results: a step it didn&apos;t record shows “not recorded”.</p>
        )}
        {r.cancel_requested_at && !ended && <p className="text-small">It&apos;s shown as cancelled once the server confirms it.</p>}
        {cancel.state === "failed" && <p role="alert" className="text-small text-danger">Couldn&apos;t cancel it. Try again.</p>}
        {endedAt && steps.data && (
          <p className="text-small text-muted">
            {`Ended: ${endedWhat(r.status, steps.data.steps)} · `}
            <When iso={endedAt} />
          </p>
        )}
      </div>
      <div className="flex min-h-0 flex-1 @max-3xl:flex-col">
        <div className="relative flex min-h-0 min-w-0 flex-1">
          {graph === null ? (
            version.isError || snapshot.isError ? (
              <p role="alert" className="p-6 text-body text-danger">The workflow it ran couldn&apos;t be read.</p>
            ) : (
              <p role="status" className="p-6 text-body text-muted">Reading the workflow it ran…</p>
            )
          ) : (
            <Canvas
              doc={graph}
              types={typeMap}
              problems={NO_PROBLEMS}
              separate={NO_PROBLEMS}
              conditional={NO_STEPS}
              editable={false}
              current={node ? node.id : null}
              focusId={keys.shown}
              focusRequest={keys.focusRequest}
              onFocusItem={keys.onFocusItem}
              onItem={onItem}
              onMove={nothing}
              onConnect={nothing}
              onLayout={nothing}
              onKeyDown={onCanvasKey}
              placing={false}
              onPlace={nothing}
              overview={!node && open !== START}
              start={{
                summary: trigger.words ? `${trigger.kind} · ${trigger.words}` : trigger.kind,
                label: `Start: ${triggerWords(r)}. Open the run's start`,
                open: open === START,
                onOpen: () => setOpen(open === START ? null : START),
                tags: unstarted ? undefined : given,
              }}
              results={unstarted ? undefined : results}
              resultsLabel="result"
            />
          )}
        </div>
        {open === START && (
          <StartDrawer
            tenantId={tenantId}
            run={r}
            onClose={() => {
              setOpen(null);
              keys.focus(item.start);
            }}
          />
        )}
        {node && graph && (
          <StepDrawer
            key={idKey(node.id)}
            node={node}
            type={typeMap.get(node.type)}
            tenantId={tenantId}
            workflowId={r.workflow_id}
            revision={null}
            steps={nodesOf(graph).map((n) => ({ id: n.id, key: n.key, title: typeMap.get(n.type)?.title ?? null }))}
            ports={portsOf(node, typeMap.get(node.type))}
            problems={[]}
            expressions={[]}
            editable={false}
            adds={[]}
            actions={READ_ONLY_ACTIONS}
            note={null}
            focusField={null}
            result={resultOf(summary)}
            onAdd={nothing}
            onDelete={nothing}
            onConnectPort={nothing}
            onPlace={nothing}
            onNudge={nothing}
            onClose={() => {
              setOpen(null);
              keys.focus(item.node(node.id));
            }}
          />
        )}
      </div>
      <ConfirmDialog
        open={cancel.state === "asking" || (cancel.state === "sending" && r.mode === "live")}
        alert
        title="Cancel this run?"
        confirmLabel="Cancel the run"
        cancelLabel="Keep it running"
        busy={cancel.state === "sending"}
        onConfirm={cancel.send}
        onCancel={cancel.keep}
      >
        It stops at its next step. What it already did against Mist and its other connections isn&apos;t undone.
      </ConfirmDialog>
    </div>
  );
}
