// SPDX-License-Identifier: Apache-2.0
// The editor (screen 1c): the draft, on a canvas, by pointer or keyboard alone (D16). Task 13 adds saving, Task 14
// problems, Task 15 publishing and versions.
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type KeyboardEvent } from "react";
import { Button } from "../../components/Button";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { LoadError } from "../../components/LoadError";
import { announce } from "../../lib/announce";
import {
  START, addAfter, asGraph, connect, deleteEdge, deleteNode, edgesOf, findNode, idKey, insertBeforeEntry, insertOnEdge,
  moveNodes, nodesOf, portsOf, sameId, type PortRef,
} from "../../lib/graph";  // prettier-ignore
import { begin, record, redo, undo, type History } from "../../lib/history";
import { CARD, layout } from "../../lib/layout";
import { useDocumentTitle } from "../../lib/title";
import {
  canEdit, nodeTypesQuery, tenantQuery, workflowQuery, type GraphDoc, type GraphEdge, type NodeType,
  type WorkflowDetail,
} from "../../lib/workflows";  // prettier-ignore
import { Canvas } from "./Canvas";
import { NAV_KEYS, isPath, navModel, pathTo, step, type NavKey } from "./canvasNav";
import { ConnectDialog } from "./ConnectDialog";
import { item, type ItemAction } from "./items";
import { StepPanel } from "./StepPanel";
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
  const [trail, setTrail] = useState<string[] | null>(null); // the path the keys came by to the focused item
  const [picker, setPicker] = useState<PickMode | null>(null);
  // Steps by identity (`idKey`, `findNode`): an item names a step's canonical id, the document its authored one.
  const keyOf = (id: string) => findNode(doc, id)?.key ?? "a step";

  const portMap = useMemo(
    () => new Map(nodesOf(doc).map((n) => [idKey(n.id), portsOf(n, typeMap.get(n.type))])),
    [doc, typeMap],
  );
  const nav = useMemo(() => navModel(doc, (id) => portMap.get(idKey(id)) ?? [], editable), [doc, portMap, editable]);
  const shown = nav.order.includes(focusId) ? focusId : START; // a deleted item's tab stop falls back to the start card
  const [connecting, setConnecting] = useState<PortRef | null>(null);
  const [asking, setAsking] = useState<{ kind: "node"; id: string } | { kind: "edge"; edge: GraphEdge } | null>(null);
  const [panel, setPanel] = useState<string | null>(null); // the step whose panel is open
  const [placing, setPlacing] = useState<string | null>(null); // the step the next click on the canvas puts there

  function focus(id: string, path: string[] | null = null) {
    setFocusId(id);
    setTrail(path);
    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
  }

  function change(next: GraphDoc, message: string, then?: string) {
    setHistory((h) => record(h, next));
    announce(message);
    if (then) focus(then);
  }

  const firstPort = (nodeId: string): PortRef | null => {
    const port = portMap.get(idKey(nodeId))?.[0];
    return port ? { node: nodeId, port } : null;
  };

  /** `A`, the toolbar's Add step, and Enter on a "+": the picker for the focused item. */
  function addFrom(id: string) {
    if (id === START || id === item.port(START, "out")) return setPicker({ kind: "after", from: null });
    if (id.startsWith("node:")) {
      const from = firstPort(id.slice(5));
      if (from) setPicker({ kind: "after", from });
      else announce(`${keyOf(id.slice(5))} ends its branch: there's no port to add after`);
      return;
    }
    if (id.startsWith("entry:")) return setPicker({ kind: "before", entry: id.slice(6) });
    if (id.startsWith("edge:")) return setPicker({ kind: "insert", edge: nav.edges.get(id)! });
    if (id.startsWith("port:")) {
      const [, node, port] = id.split(":");
      setPicker({ kind: "after", from: { node: node!, port: port! } });
    }
  }

  function connectFrom(id: string) {
    if (id.startsWith("port:") && !id.startsWith(`port:${START}:`)) {
      const [, node, port] = id.split(":");
      return setConnecting({ node: node!, port: port! });
    }
    if (id.startsWith("edge:")) return setConnecting(nav.edges.get(id)!.from as PortRef);
    if (id.startsWith("node:")) {
      const from = firstPort(id.slice(5));
      if (from) setConnecting(from);
    }
  }

  function askDelete(id: string) {
    if (id.startsWith("node:")) setAsking({ kind: "node", id: id.slice(5) });
    if (id.startsWith("edge:")) setAsking({ kind: "edge", edge: nav.edges.get(id)! });
  }

  function confirmDelete() {
    if (!asking) return;
    if (asking.kind === "node") {
      const { doc: next, healed } = deleteNode(doc, asking.id);
      // Focus goes to the step it came after (its own items are gone with it), or to the start card.
      const inbound = edgesOf(doc).find((e) => sameId(e.to.node, asking.id));
      const back = inbound ? item.node(inbound.from.node) : START;
      if (panel === asking.id) setPanel(null);
      change(next, `Deleted ${keyOf(asking.id)}${healed ? `; ${keyOf(healed.from.node)} now leads to ${keyOf(healed.to.node)}` : ""}`, back);
    } else {
      change(deleteEdge(doc, asking.edge), `Deleted the edge from ${keyOf(asking.edge.from.node)} to ${keyOf(asking.edge.to.node)}`, item.node(asking.edge.from.node));
    }
    setAsking(null);
  }

  function nudge(nodeId: string, key: NavKey) {
    const n = findNode(doc, nodeId);
    if (!n) return;
    const d = { ArrowUp: [0, -20], ArrowDown: [0, 20], ArrowLeft: [-20, 0], ArrowRight: [20, 0], Home: [0, 0] }[key];
    change(moveNodes(doc, new Map([[nodeId, { x: (n.position?.x ?? 0) + d[0]!, y: (n.position?.y ?? 0) + d[1]! }]])), `Moved ${n.key}`);
  }

  /** The click that ends "Place on the canvas…": the step, centred on it (WCAG 2.5.7). Never on a read-only canvas. */
  function place(at: { x: number; y: number }) {
    if (!placing || !editable) return;
    const id = placing;
    setPlacing(null);
    change(moveNodes(doc, new Map([[id, { x: at.x - CARD.width / 2, y: at.y - CARD.height / 2 }]])), `Placed ${keyOf(id)}`, item.node(id));
  }

  /** Escape stops placing first, before it closes a panel or a picker. */
  function onEditorKeyCapture(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Escape" || !placing) return;
    e.stopPropagation();
    e.preventDefault();
    setPlacing(null);
    announce("Not placed");
  }

  function onCanvasKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!(e.target as HTMLElement).dataset.item || e.altKey) return;
    // From the item focus is meant to be on: a key moves focus a frame later (the canvas draws it first), and a key
    // pressed before then (auto-repeat, a quick hand) starts where the last one left it, not where the browser's
    // focus still is.
    const id = shown;
    const plain = !e.ctrlKey && !e.metaKey;
    if (NAV_KEYS.includes(e.key) && plain) {
      e.preventDefault();
      if (e.shiftKey && editable && id.startsWith("node:")) return nudge(id.slice(5), e.key as NavKey);
      // The path the keys came by while it still holds (at a join, the branch taken); else the walk's own path.
      const path = trail && trail.at(-1) === id && isPath(nav, trail) ? trail : pathTo(nav, id);
      const next = step(nav, path, e.key as NavKey);
      if (next.at(-1) !== id) focus(next.at(-1)!, next);
      return;
    }
    if (!editable || !plain) return;
    if (e.key === "a" || e.key === "A") {
      e.preventDefault();
      addFrom(id);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      askDelete(id);
    } else if (e.key === "c" || e.key === "C") {
      e.preventDefault();
      connectFrom(id);
    }
  }

  /** Ctrl or Cmd+Z undoes, with Shift redoes (D17: local). Not while typing, nor behind a dialog. Focus stays in the
   * editor: on the focused item while it survives, else on its nearest surviving item back along the path the keys
   * would take to it, else on the start card (the owner's review of M3). */
  function onEditorKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z" || !editable) return;
    const t = e.target as HTMLElement;
    if (t.closest("input, textarea, select, dialog")) return;
    e.preventDefault();
    const next = e.shiftKey ? redo(history) : undo(history);
    if (next === history) return;
    setHistory(next);
    announce(e.shiftKey ? "Redone" : "Undone");
    const after = next.present;
    const nextNav = navModel(after, (id) => {
      const n = findNode(after, id);
      return n ? portsOf(n, typeMap.get(n.type)) : [];
    }, editable);  // prettier-ignore
    const panelGone = panel !== null && !findNode(after, panel);
    if (panelGone) setPanel(null);
    // What had focus: a canvas item; the open panel (left there while its step survives); or something else in the
    // editor (left where it is).
    const inPanel = panel !== null && !t.dataset.item && t.closest("aside") !== null;
    if (inPanel && !panelGone) return;
    const held = inPanel ? item.node(panel) : (t.dataset.item ?? null);
    if (held === null) return;
    // A surviving item keeps its element and its focus: asking again would steal it back a frame later from
    // wherever the person has since moved it.
    if (nextNav.order.includes(held)) return;
    const back = (trail && trail.at(-1) === held ? trail : pathTo(nav, held)).slice(0, -1).reverse();
    focus(back.find((id) => nextNav.order.includes(id)) ?? START);
  }

  function onItem(action: ItemAction) {
    if (action.kind === "open") return setPanel(action.node);
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
    if (next) change(next, `Connected ${keyOf(from.node)} to ${keyOf(to)}`, item.edge({ from, to: { node: to } }));
    else announce(`${keyOf(from.node)} can't lead to ${keyOf(to)}: that would repeat an edge or close a loop`);
  }

  const healed = asking?.kind === "node" ? deleteNode(doc, asking.id).healed : null;
  const open = panel ? findNode(doc, panel) : undefined;

  return (
    <div className="flex min-h-0 flex-1 flex-col" onKeyDown={onEditorKey} onKeyDownCapture={onEditorKeyCapture}>
      <Toolbar tenantId={tenantId} name={workflow.name}>
        {editable ? (
          <Button size="md" aria-keyshortcuts="A" onClick={() => addFrom(shown)}>
            ＋ Add step <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">A</kbd>
          </Button>
        ) : (
          <span className="text-small text-muted">Read only: your role can&apos;t edit workflows</span>
        )}
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <div className="relative flex min-h-0 min-w-0 flex-1">
          {placing && editable && (
            // Over the canvas's top edge, never above it: the canvas doesn't move when placing starts or ends, so a
            // step placed with a click stays under the click (ledger M13).
            <div data-canvas-overlay className="absolute inset-x-0 top-0 z-10 flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
              <span className="grow">Click an empty place on the canvas to put {keyOf(placing)} there.</span>
              <Button size="sm" onClick={() => setPlacing(null)}>Cancel</Button>
            </div>
          )}
          <Canvas
          doc={doc}
          types={typeMap}
          problems={new Map()}
          separate={new Map()}
          editable={editable}
          current={panel}
          focusId={shown}
          focusRequest={focusRequest}
          onFocusItem={(id) => {
            setFocusId(id);
            setTrail((t) => (t?.at(-1) === id ? t : null));
          }}
          onItem={onItem}
          onMove={(positions) => change(moveNodes(doc, positions), "Moved")}
          onConnect={onConnect}
          onLayout={() => change(moveNodes(doc, layout(doc)), "Laid out the steps")}
          onKeyDown={onCanvasKey}
          placing={editable && placing !== null}
          onPlace={place}
          overview={!open}
          />
        </div>
        {open && (
          <StepPanel
            node={open}
            type={typeMap.get(open.type)}
            ports={portMap.get(idKey(open.id)) ?? []}
            problems={null}
            expressions={[]}
            editable={editable}
            onDelete={() => setAsking({ kind: "node", id: open.id })}
            onConnectPort={(port) => setConnecting({ node: open.id, port })}
            onPlace={() => {
              setPlacing(open.id);
              announce(`Click an empty place on the canvas to put ${open.key} there`);
            }}
            onNudge={(key) => nudge(open.id, key)}
            onClose={() => {
              setPanel(null);
              focus(item.node(open.id));
            }}
          />
        )}
      </div>
      {picker && (
        <StepPicker
          mode={picker}
          types={types}
          onPick={onPick}
          onConnect={picker.kind === "after" && picker.from ? () => setConnecting(picker.from) : undefined}
          onClose={() => setPicker(null)}
        />
      )}
      {connecting && (
        <ConnectDialog
          doc={doc}
          types={typeMap}
          from={connecting}
          onConnect={(to) => onConnect(connecting, to)}
          onClose={() => setConnecting(null)}
        />
      )}
      <ConfirmDialog
        open={asking !== null}
        title={asking?.kind === "edge" ? "Delete an edge" : "Delete a step"}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setAsking(null)}
      >
        {asking?.kind === "node" && (
          <>
            {keyOf(asking.id)} and its edges are deleted.
            {healed && ` ${keyOf(healed.from.node)} will lead to ${keyOf(healed.to.node)}.`} Other steps that read its
            output will show a problem.
          </>
        )}
        {asking?.kind === "edge" && `${keyOf(asking.edge.to.node)} will no longer follow ${keyOf(asking.edge.from.node)}.`}
      </ConfirmDialog>
    </div>
  );
}
