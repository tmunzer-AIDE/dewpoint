// SPDX-License-Identifier: Apache-2.0
// The editor (screen 1c): the draft, on a canvas. Task 12 adds the keyboard, Task 13 saving, Task 14 problems, Task 15
// publishing and versions.
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button } from "../../components/Button";
import { LoadError } from "../../components/LoadError";
import { announce } from "../../lib/announce";
import {
  START, addAfter, asGraph, connect, insertBeforeEntry, insertOnEdge, moveNodes, nodesOf, type PortRef,
} from "../../lib/graph";  // prettier-ignore
import { begin, record, type History } from "../../lib/history";
import { layout } from "../../lib/layout";
import { useDocumentTitle } from "../../lib/title";
import {
  canEdit, nodeTypesQuery, tenantQuery, workflowQuery, type GraphDoc, type NodeType, type WorkflowDetail,
} from "../../lib/workflows";  // prettier-ignore
import { Canvas } from "./Canvas";
import { item, type ItemAction } from "./items";
import { StepPicker, type PickMode } from "./StepPicker";
import { Toolbar } from "./Toolbar";

export function EditorPage({ tenantId, workflowId }: { tenantId: string; workflowId: string }) {
  const workflow = useQuery(workflowQuery(tenantId, workflowId));
  const types = useQuery(nodeTypesQuery);
  const tenant = useQuery(tenantQuery(tenantId));
  useDocumentTitle(workflow.data?.name ?? "Workflow");
  if (workflow.isError) return <section className="p-6"><LoadError what="This workflow" /></section>;
  if (types.isError) return <section className="p-6"><LoadError what="The step types" /></section>;
  if (!workflow.data || !types.data || !tenant.data) return <p className="p-6 text-body text-muted">Loading…</p>;
  return <Editor tenantId={tenantId} workflow={workflow.data} types={types.data} role={tenant.data.role ?? null} />;
}

function Editor({ tenantId, workflow, types, role }: { tenantId: string; workflow: WorkflowDetail; types: NodeType[]; role: string | null }) {
  const typeMap = useMemo(() => new Map(types.map((t) => [t.ref, t])), [types]);
  const [history, setHistory] = useState<History<GraphDoc>>(() => begin(asGraph(workflow.draft)));
  const doc = history.present;
  const editable = canEdit(role);
  const [focusId, setFocusId] = useState<string>(START);
  const [focusRequest, setFocusRequest] = useState<{ id: string; n: number } | null>(null);
  const [picker, setPicker] = useState<PickMode | null>(null);
  const keyOf = (id: string) => nodesOf(doc).find((n) => n.id === id)?.key ?? "a step";

  function focus(id: string) {
    setFocusId(id);
    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
  }

  function change(next: GraphDoc, message: string, then?: string) {
    setHistory((h) => record(h, next));
    announce(message);
    if (then) focus(then);
  }

  function onItem(action: ItemAction) {
    if (!editable) return;
    if (action.kind === "after") setPicker({ kind: "after", from: action.from });
    if (action.kind === "insert") setPicker({ kind: "insert", edge: action.edge });
    if (action.kind === "before") setPicker({ kind: "before", entry: action.entry });
  }

  function onPick(type: NodeType) {
    if (!picker) return;
    const made =
      picker.kind === "after" ? addAfter(doc, picker.from, type)
      : picker.kind === "insert" ? insertOnEdge(doc, picker.edge, type)
      : insertBeforeEntry(doc, picker.entry, type);  // prettier-ignore
    if (!made) return;
    const where =
      picker.kind === "after" ? (picker.from ? `after ${keyOf(picker.from.node)}` : "at the start")
      : picker.kind === "insert" ? `between ${keyOf(picker.edge.from.node)} and ${keyOf(picker.edge.to.node)}`
      : `before ${keyOf(picker.entry)}`;  // prettier-ignore
    change(made.doc, `Added ${made.node.key} ${where}`, item.node(made.node.id));
  }

  function onConnect(from: PortRef, to: string) {
    const next = connect(doc, from, to);
    if (next) change(next, `Connected ${keyOf(from.node)} to ${keyOf(to)}`);
    else announce(`${keyOf(from.node)} can't lead to ${keyOf(to)}: that would repeat an edge or close a loop`);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Toolbar tenantId={tenantId} name={workflow.name}>
        {editable ? (
          <Button size="md" aria-keyshortcuts="A" onClick={() => setPicker({ kind: "after", from: null })}>
            ＋ Add step <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">A</kbd>
          </Button>
        ) : (
          <span className="text-small text-muted">Read only: your role can&apos;t edit workflows</span>
        )}
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <Canvas
          doc={doc}
          types={typeMap}
          problems={new Map()}
          separate={new Map()}
          editable={editable}
          current={null}
          focusId={focusId}
          focusRequest={focusRequest}
          onFocusItem={setFocusId}
          onItem={onItem}
          onMove={(positions) => change(moveNodes(doc, positions), "Moved")}
          onConnect={onConnect}
          onLayout={() => change(moveNodes(doc, layout(doc)), "Laid out the steps")}
        />
      </div>
      {picker && (
        <StepPicker mode={picker} types={types} onPick={onPick} onClose={() => setPicker(null)} />
      )}
    </div>
  );
}
