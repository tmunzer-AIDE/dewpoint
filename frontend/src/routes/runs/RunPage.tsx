// SPDX-License-Identifier: Apache-2.0
// A run's page (editor 4e-1; the runs design §5.3, §5.4; the RunFailed, RunRunning and RunOther boards), laid out like
// the editor (the owner's answer 6): the compact rail, the run's bar, its banner, and the graph it ran on the read-only
// canvas, each step's result beside its card, walked with the editor's keys (D16). It's read while it runs
// (useRunReads). A step's result opens in the editor's drawer, read only, its Result tab first; a failed run opens on
// its failed step (the owner's answer 6), and Close gives focus back to its card. A run past its tenant's retention, or
// an id that never was, is said to be neither, with Back to Runs; a run read while its tenant is erased says why it
// can't be (§5.5).
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
import { Button, LINK_BUTTON } from "../../components/Button";
import { When } from "../../components/When";
import { ApiError } from "../../lib/client";
import { findNode, idKey, nodesOf, portsOf } from "../../lib/graph";
import { isEnded, type RunStepSummary } from "../../lib/runs";
import { runId } from "../../lib/runStatus";
import { draftSnapshotQuery } from "../../lib/simulations";
import { useDocumentTitle } from "../../lib/title";
import { versionQuery } from "../../lib/triggers";
import { timeOf } from "../../lib/when";
import { nodeTypesQuery, type GraphDoc } from "../../lib/workflows";
import { Canvas } from "../editor/Canvas";
import { NAV_KEYS, type NavKey } from "../editor/canvasNav";
import { READ_ONLY_ACTIONS } from "../editor/drawer/context";
import { StepDrawer } from "../editor/drawer/StepDrawer";
import { item, type ItemAction } from "../editor/items";
import { endedWhat } from "../editor/simulation/lifecycle";
import { tagsOf, type SimTag } from "../editor/simulation/results";
import { useCanvasNav } from "../editor/useCanvasNav";
import { RunBanner, RunBar } from "./RunBar";
import { StepResult } from "./RunResult";
import { triggerOf, triggerWords } from "./trigger";
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

const NONE: GraphDoc = { graph_format: 1, nodes: [], edges: [] };
const NO_STEPS: ReadonlySet<string> = new Set();
const NO_PROBLEMS = new Map();
const nothing = () => undefined;

export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: string }) {
  useDocumentTitle(`Run ${runId(id)}`);
  const { run, steps } = useRunReads(tenantId, id);
  const r = run.data;
  const types = useQuery(nodeTypesQuery);
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
  const [open, setOpen] = useState<string | null | undefined>(undefined);
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
    if (action.kind === "open") setOpen(action.node);
  };
  return (
    <div className="@container flex min-h-0 flex-1 flex-col">
      <RunBar tenantId={tenantId} run={r} version={version.data?.number ?? null} />
      <div className="flex flex-col gap-2 border-b border-line bg-surface px-5 py-2.5">
        {run.isRefetchError && (
          <p className="flex flex-wrap items-center gap-2 text-small text-muted">
            {`Couldn't be refreshed · as of ${timeOf(run.dataUpdatedAt)}`}
            <Button size="sm" onClick={() => void run.refetch()}>Try again</Button>
          </p>
        )}
        <RunBanner run={r} />
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
              overview={!node}
              start={{
                summary: trigger.words ? `${trigger.kind} · ${trigger.words}` : trigger.kind,
                label: `Start: ${triggerWords(r)}. Open the run's start`,
                open: false,
                onOpen: nothing,
                tags: given,
              }}
              results={results}
              resultsLabel="result"
            />
          )}
        </div>
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
            result={
              <StepResult
                tenantId={tenantId}
                runId={id}
                summary={summary}
                max={summary ? attemptsOf(summary) : null}
                ended={ended}
                several={summary && <p className="text-small">{tagsFor(summary).map((t) => t.text).join(" · ")}</p>}
              />
            }
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
    </div>
  );
}
