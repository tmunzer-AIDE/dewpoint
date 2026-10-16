// SPDX-License-Identifier: Apache-2.0
// A run's page (editor 4e-1; the runs design §5.3, §5.4; the RunFailed and RunOther boards), laid out like the editor
// (the owner's answer 6): the compact rail, and a bar naming the run, its workflow and its short id, with the way back
// to Runs. A run past its tenant's retention, or an id that never was, is said to be neither, with Back to Runs; a run
// read while its tenant is erased says why it can't be (§5.5).
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Button, LINK_BUTTON } from "../../components/Button";
import { ApiError } from "../../lib/client";
import { runQuery } from "../../lib/runs";
import { runId } from "../../lib/runStatus";
import { useDocumentTitle } from "../../lib/title";

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

export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: string }) {
  useDocumentTitle(`Run ${runId(id)}`);
  const run = useQuery(runQuery(tenantId, id));
  const r = run.data;
  // Only a run never read says why it isn't shown: a read that fails later keeps what was read.
  if (!r) return run.isError ? <Unread tenantId={tenantId} id={id} error={run.error} retry={() => void run.refetch()} /> : <p role="status" className="p-6 text-body text-muted">Reading the run…</p>;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
        <Link to="/t/$tenantId/runs" params={{ tenantId }} className="text-small text-muted hover:text-ink">← Runs</Link>
        <h1 className="min-w-0 truncate text-body-lg font-semibold">{r.workflow_name ?? "—"}</h1>
        <span className="font-mono text-small">{`run ${runId(r.id)}`}</span>
      </div>
    </div>
  );
}
