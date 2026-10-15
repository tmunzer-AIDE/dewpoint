// SPDX-License-Identifier: Apache-2.0
// A step's Test tab (4d-1c; the simulation design §7.6; the TestTab, TestResult and TestOther boards), beside Setup and
// Options, for editors: the values the step reads, its seed contract, read at the draft's saved revision; a step that
// can't run alone says why, in the server's words, and offers the workflow's simulation instead. A draft with problems
// is read once they're fixed, as admission reads it. "◌ Simulate step" saves first; when the save moved the draft, the
// contract is read again and shown before anything is sent: a new revision is never paired with an older contract.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../../../components/Button";
import { ApiError } from "../../../lib/client";
import { sameId } from "../../../lib/graph";
import { freeze, seedContractQuery, type Frozen } from "../../../lib/simulations";
import type { GraphDoc, GraphNode, NodeType } from "../../../lib/workflows";
import { Refusal } from "./Refusal";
import { SeedField } from "./SeedField";
import { collect, initialOf, titleOf, type SeedInput } from "./seeds";
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

const missingWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value is" : "values are"} missing.`;
const unreadWords = (n: number) => `Not simulated: ${n} ${n === 1 ? "value isn't" : "values aren't"} valid JSON.`;

export function TestTab(props: TestTabProps) {
  const { tenantId, workflowId, node, doc, types, revision, session, blocked, onSave, onStart, onSimulateWorkflow, onGoTo, onShowProblems } = props;
  // The contract at the saved revision; while a newer one is read, the older stays shown (it's never sent with it).
  const contract = useQuery({ ...seedContractQuery(tenantId, workflowId, node.id, revision), placeholderData: keepPreviousData });
  const [inputs, setInputs] = useState<Record<string, SeedInput>>({});
  const [checked, setChecked] = useState<{ missing: string[]; problems: Record<string, string> } | null>(null);
  const [moved, setMoved] = useState<{ to: number; before: Set<string> } | null>(null); // a save moved the draft
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
  // The values the server refused for this step's test, on their fields; one with no field, above them.
  const local = session.local;
  const refused = local.kind === "refused" && local.frozen.body.target && sameId(local.frozen.body.target.step_id, node.id) ? local.error : null;
  const seedProblems = refused && Array.isArray((refused.body as { problems?: unknown } | null)?.problems)
    ? ((refused.body as { problems: { pointer: string; message: string }[] }).problems)
    : null;  // prettier-ignore
  const pointers = new Set(c.entries.map((e) => e.pointer));
  const added = moved && moved.to === c.draft_revision ? c.entries.filter((e) => !moved.before.has(e.pointer)).length : 0;
  const errorOf = (pointer: string) =>
    checked?.problems[pointer] ?? seedProblems?.find((p) => p.pointer === pointer)?.message ?? null;
  const missing = checked ? checked.missing.filter((p) => p in checked.problems).length : 0;
  const unread = checked ? Object.keys(checked.problems).length - missing : 0;

  async function simulate() {
    setChecked(null);
    const saved = await onSave();
    if (saved === null) return;
    if (saved !== c.draft_revision) {
      setMoved({ to: saved, before: pointers });
      return;
    }
    const out = collect(c, inputs, node.key);
    if ("problems" in out) return setChecked(out);
    setMoved(null);
    onStart(freeze(saved, { target: { step_id: node.id, values: out.values, absent: out.absent } }));
  }

  return (
    <>
      <p className="text-small">
        Runs <span className="font-mono">{node.key}</span> alone, with these values in place of what the steps before it would give.
        Nothing is sent.
      </p>
      {moved && moved.to === c.draft_revision && (
        <p role="status" className="text-small">
          {`Saving moved the draft to revision ${moved.to}${added > 0 ? `, and ${node.key} now reads ${added === 1 ? "one more value" : `${added} more values`}` : ""}. Check the values, then simulate.`}
        </p>
      )}
      {refused && !seedProblems && (
        <Refusal error={refused} doc={doc} onGoTo={onGoTo} onShowProblems={onShowProblems} onTryAgain={() => void session.checkAgain()} />
      )}
      {seedProblems && seedProblems.some((p) => !pointers.has(p.pointer)) && (
        <div className="flex flex-col gap-1 text-small">
          <p className="font-semibold">Not simulated</p>
          {seedProblems.filter((p) => !pointers.has(p.pointer)).map((p) => <p key={p.pointer}>{`${p.pointer}: ${p.message}`}</p>)}
        </div>
      )}
      {(missing > 0 || unread > 0) && (
        <p role="alert" className="text-small text-danger">{missing > 0 ? missingWords(missing) : unreadWords(unread)}</p>
      )}
      <section aria-labelledby="test-values" className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between gap-3">
          <h3 id="test-values" className="text-small font-semibold">Values it reads</h3>
          <span className="text-meta text-muted">{`revision ${c.draft_revision}`}</span>
        </div>
        {c.entries.length === 0 && <p className="text-small text-muted">It reads no values from before it.</p>}
        {c.entries.map((e) => (
          <SeedField
            key={e.pointer} entry={e} title={titleOf(e.pointer, doc, types, node.id)} input={inputs[e.pointer] ?? initialOf(e)}
            error={errorOf(e.pointer)} isNew={moved && moved.to === c.draft_revision && !moved.before.has(e.pointer) ? moved.to : null}
            onChange={(input) => {
              setInputs({ ...inputs, [e.pointer]: input });
              if (checked?.problems[e.pointer]) setChecked({ ...checked, problems: Object.fromEntries(Object.entries(checked.problems).filter(([p]) => p !== e.pointer)) });
            }}
          />
        ))}
      </section>
      <div className="flex flex-col items-start gap-1.5">
        <Button variant="simulate" size="md" disabled={blocked} onClick={() => void simulate()}>◌ Simulate step</Button>
        <p className="text-small text-muted">{`Each value is checked against what ${node.key} reads.`}</p>
      </div>
    </>
  );
}
