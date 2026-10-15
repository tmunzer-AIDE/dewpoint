// SPDX-License-Identifier: Apache-2.0
// A step's Test tab (4d-1c; the simulation design §7.6; the TestTab, TestResult and TestOther boards), beside Setup and
// Options, for editors: the values the step reads, its seed contract, read at the draft's saved revision; a step that
// can't run alone says why, in the server's words, and offers the workflow's simulation instead. A draft with problems
// is read once they're fixed, as admission reads it.
import { useQuery } from "@tanstack/react-query";
import { Button } from "../../../components/Button";
import { ApiError } from "../../../lib/client";
import { seedContractQuery, type Frozen } from "../../../lib/simulations";
import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
import { Refusal } from "./Refusal";
import type { SimulationSession } from "./useSimulation";

export interface TestTabProps {
  tenantId: string;
  workflowId: string;
  node: GraphNode;
  doc: GraphDoc;
  types: Map<string, NodeType>;
  revision: number; // the draft's saved revision: the contract is read at it
  session: SimulationSession;
  blocked: boolean; // Simulate waits: a conflict, a save, a simulation not ended
  onSave: () => Promise<number | null>; // the edits settled and saved: the revision saved, else null (the editor says why)
  onStart: (frozen: Frozen) => void;
  onSimulateWorkflow: () => void;
  onGoTo: (stepId: string) => void;
  onShowProblems: () => void;
}

export function TestTab({ tenantId, workflowId, node, doc, revision, onSimulateWorkflow, onGoTo, onShowProblems }: TestTabProps) {
  const contract = useQuery(seedContractQuery(tenantId, workflowId, node.id, revision));
  if (contract.isPending) return <p className="text-small text-muted">Reading the values it reads…</p>;
  if (contract.isError) {
    const e = contract.error;
    if (e instanceof ApiError && e.code === "invalid") {
      return <Refusal error={e} doc={doc} heading={null} onGoTo={onGoTo} onShowProblems={onShowProblems} onTryAgain={() => void contract.refetch()} />;
    }
    if (e instanceof ApiError && e.status === 404) {
      return <p className="text-small text-muted">This step isn&apos;t in the saved draft yet: its values are read once it&apos;s saved.</p>;
    }
    return (
      <p className="flex flex-wrap items-center gap-2 text-small">
        The values it reads couldn&apos;t be read.
        <Button size="sm" onClick={() => void contract.refetch()}>Read them again</Button>
      </p>
    );
  }
  const c = contract.data;
  if (c.refused !== null) {
    return (
      <>
        <p className="text-small">{c.refused}</p>
        <div>
          <Button variant="simulate" size="md" onClick={onSimulateWorkflow}>◌ Simulate workflow</Button>
        </div>
      </>
    );
  }
  return (
    <>
      <p className="text-small">
        Runs <span className="font-mono">{node.key}</span> alone, with these values in place of what the steps before it would give.
        Nothing is sent.
      </p>
      <section aria-labelledby="test-values" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h3 id="test-values" className="text-small font-semibold">Values it reads</h3>
          <span className="text-meta text-muted">{`revision ${c.draft_revision}`}</span>
        </div>
      </section>
    </>
  );
}
