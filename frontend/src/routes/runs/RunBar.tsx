// SPDX-License-Identifier: Apache-2.0
// A run's bar and banner (editor 4e-1; the runs design §5.3; the RunFailed, RunRunning and RunOther boards). The bar:
// the way back to Runs, the workflow, the run's short id and Copy id, its status and what it was (live in orange,
// D3; a simulation hatched, D2), its version or a draft's revision, its trigger, start and duration, and Open the
// workflow ("Open in the editor" for a draft simulation). The banner says what a live run did, or what a simulation
// proves, in the present while it runs.
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Button, LINK_BUTTON } from "../../components/Button";
import { ModeChip, RunStatusChip } from "../../components/RunChips";
import { When } from "../../components/When";
import { announce } from "../../lib/announce";
import { isEnded, type Run } from "../../lib/runs";
import { duration, runId } from "../../lib/runStatus";
import { SimBanner } from "../editor/simulation/SimBanner";
import { triggerWords } from "./trigger";

/** The run's facts in a line: "version 2 · webhook, Mist events · started today 09:41:12 · 38 s". */
function Facts({ run, version }: { run: Run; version: number | null }) {
  const ended = isEnded(run.status);
  const lead = run.draft_snapshot_id !== null ? `draft revision ${run.draft_revision}` : version !== null ? `version ${version}` : null;
  const start = run.started_at ?? run.queued_at;
  const lasted = duration(run.started_at, ended ? run.ended_at : new Date(Date.now()).toISOString());
  return (
    <span className="grow text-small text-muted">
      {lead && `${lead} · `}
      {triggerWords(run)}
      {start && <> · {run.started_at ? "started" : "queued"} <When iso={start} /></>}
      {lasted && ` · ${lasted}${ended ? "" : " so far"}`}
    </span>
  );
}

export function RunBar({ tenantId, run, version, children }: { tenantId: string; run: Run; version: number | null; children?: ReactNode }) {
  const copy = () => navigator.clipboard.writeText(run.id).then(() => announce("Copied the run's id"), () => announce("The run's id couldn't be copied"));
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
      <Link to="/t/$tenantId/runs" params={{ tenantId }} className="text-small text-muted hover:text-ink">← Runs</Link>
      <h1 className="min-w-0 truncate text-body-lg font-semibold">{run.workflow_name ?? "—"}</h1>
      <span className="font-mono text-small">{`run ${runId(run.id)}`}</span>
      <Button size="sm" onClick={() => void copy()}>Copy id</Button>
      <RunStatusChip status={run.status} />
      <ModeChip mode={run.mode} draft={run.draft_snapshot_id !== null} />
      <Facts run={run} version={version} />
      {children}
      <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: run.workflow_id }} className={LINK_BUTTON}>
        {run.draft_snapshot_id !== null ? "Open in the editor" : "Open the workflow"}
      </Link>
    </div>
  );
}

export function RunBanner({ run }: { run: Run }) {
  const ended = isEnded(run.status);
  if (run.mode === "live") {
    return (
      <p role="note" className="rounded-lg border border-live bg-live-bg px-3 py-2 text-small text-ink">
        <strong className="text-live">Live run.</strong>
        {` It ${ended ? "acted" : "acts"} for real: steps marked `}
        <span className="rounded-sm border border-live bg-surface px-1.5 text-live">sent</span>
        {" called their connections."}
      </p>
    );
  }
  return (
    <SimBanner>
      <p>
        <strong>Simulated.</strong>
        {` Nothing ${ended ? "was" : "is"} sent. `}
        {run.draft_snapshot_id !== null ? `The draft's revision ${run.draft_revision} ran, not a published version.` : "Results don't prove the live call will succeed."}
      </p>
    </SimBanner>
  );
}
