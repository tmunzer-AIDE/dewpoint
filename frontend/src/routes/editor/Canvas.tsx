// SPDX-License-Identifier: Apache-2.0
// The canvas (1c): React Flow draws the document; the editor owns it. React Flow's own keyboard handling is off
// (D16; 4b ruling 15): its arrow keys move nodes, its Delete removes them, and Tab would visit every node. The
// canvas is one roving tab stop instead; Task 12 adds its keys.
import "@xyflow/react/dist/base.css";
import "./canvas.css";
import {
  Background, BackgroundVariant, MiniMap, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow, useViewport,
  type Edge, type EdgeTypes, type Node, type NodeChange, type NodeTypes,
} from "@xyflow/react";  // prettier-ignore
import { useCallback, useEffect, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import { Button } from "../../components/Button";
import { START, drawableEdges, entries, nodesOf, portOf, portsOf, pos, startPosition, type PortRef } from "../../lib/graph";
import { CARD } from "../../lib/layout";
import type { GraphDoc, NodeType } from "../../lib/workflows";
import { FlowEdge, type FlowData } from "./FlowEdge";
import { item, type ItemAction } from "./items";
import { StartNode, type StartData } from "./StartCard";
import { StepNode, type Problems, type StepData } from "./StepCard";

const nodeTypes = { step: StepNode, start: StartNode } satisfies NodeTypes;
const edgeTypes = { flow: FlowEdge } satisfies EdgeTypes;
const NONE: Problems = { errors: 0, warnings: 0 };
// Every card's size before React Flow measures it: a node without one is hidden until measured, so a step just added
// couldn't take focus (ledger M11).
const SIZE = { initialWidth: CARD.width, initialHeight: CARD.height };

export interface CanvasProps {
  doc: GraphDoc;
  types: Map<string, NodeType>;
  problems: Map<string, Problems>;
  separate: Map<string, number>;
  editable: boolean;
  current: string | null; // the step whose panel is open
  focusId: string; // the roving tab stop's item
  focusRequest: { id: string; n: number } | null; // move focus there once drawn
  onFocusItem: (id: string) => void;
  onItem: (action: ItemAction) => void;
  onMove: (positions: Map<string, { x: number; y: number }>) => void;
  onConnect: (from: PortRef, to: string) => void;
  onLayout: () => void;
  onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void;
}

/** What React Flow draws: the start card, each step, an edge from the start card to each entry step, and each edge
 * whose ends exist, once (`drawableEdges`: an imported draft may hold others, which the problems name). */
function build(p: CanvasProps): { nodes: Node[]; edges: Edge[] } {
  const used = new Map<string, string[]>();
  for (const e of drawableEdges(p.doc)) used.set(e.from.node, [...(used.get(e.from.node) ?? []), portOf(e)]);
  const keyOf = new Map(nodesOf(p.doc).map((n) => [n.id, n.key]));
  const start: StartData = { empty: nodesOf(p.doc).length === 0, focusId: p.focusId, editable: p.editable, onItem: p.onItem };
  const nodes: Node[] = [
    { id: START, type: "start", position: startPosition(p.doc), draggable: false, selectable: false, data: start, ...SIZE },
    ...nodesOf(p.doc).map((n): Node => {
      const type = p.types.get(n.type);
      const data: StepData = {
        node: n, type, ports: portsOf(n, type), connected: used.get(n.id) ?? [], problems: p.problems.get(n.id) ?? NONE,
        separate: p.separate.get(n.id) ?? 0, current: p.current === n.id, focusId: p.focusId, editable: p.editable,
        onItem: p.onItem,
      };  // prettier-ignore
      return { id: n.id, type: "step", position: pos(n), draggable: p.editable, selectable: false, data, ...SIZE };
    }),
  ];
  const flow = (id: string, label: string, action: ItemAction): FlowData => ({ item: id, label, action, focusId: p.focusId, editable: p.editable, onItem: p.onItem });
  const edges: Edge[] = [
    ...entries(p.doc).map((n): Edge => ({
      id: item.entry(n.id), source: START, sourceHandle: "out", target: n.id, type: "flow",
      data: flow(item.entry(n.id), `Insert a step before ${n.key}`, { kind: "before", entry: n.id }),
    })),
    ...drawableEdges(p.doc).map((e): Edge => ({
      id: item.edge(e), source: e.from.node, sourceHandle: portOf(e), target: e.to.node, type: "flow",
      data: flow(item.edge(e), `Insert a step between ${keyOf.get(e.from.node) ?? "a step"} and ${keyOf.get(e.to.node) ?? "a step"}`, { kind: "insert", edge: e }),
    })),
  ];  // prettier-ignore
  return { nodes, edges };
}

function Flow(p: CanvasProps) {
  const flow = useReactFlow();
  const { zoom } = useViewport();
  const container = useRef<HTMLDivElement>(null);
  const built = useMemo(() => build(p), [p]);
  const [nodes, setNodes] = useState(built.nodes);
  // A rebuilt node keeps the size React Flow measured: one without it is hidden until measured again, and a press
  // that re-renders the editor (focus moves to what was pressed) would then release over the pane (ledger M11).
  useEffect(
    () =>
      setNodes((drawn) => {
        const sizes = new Map(drawn.map((n) => [n.id, n.measured]));
        return built.nodes.map((n) => {
          const measured = sizes.get(n.id);
          return measured ? { ...n, measured } : n;
        });
      }),
    [built.nodes],
  );
  // Only drags move cards here; the document changes when a drag ends (onNodeDragStop).
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((ns) => applyNodeChanges(changes.filter((c) => c.type === "position" || c.type === "dimensions"), ns)),
    [],
  );

  /** Brings an item into view when it's outside the canvas, keeping the zoom. */
  const reveal = useCallback(
    (el: HTMLElement) => {
      const box = container.current?.getBoundingClientRect();
      if (!box) return;
      const r = el.getBoundingClientRect();
      if (r.left >= box.left && r.right <= box.right && r.top >= box.top && r.bottom <= box.bottom) return;
      const v = flow.getViewport();
      void flow.setViewport(
        { x: v.x + (box.left + box.width / 2 - (r.left + r.width / 2)), y: v.y + (box.top + box.height / 2 - (r.top + r.height / 2)), zoom: v.zoom },
        { duration: 0 },
      );
    },
    [flow],
  );

  useEffect(() => {
    if (!p.focusRequest) return;
    const id = p.focusRequest.id;
    const frame = requestAnimationFrame(() => {
      const el = container.current?.querySelector<HTMLElement>(`[data-item="${CSS.escape(id)}"]`);
      if (!el) return;
      el.focus({ preventScroll: true });
      reveal(el);
    });
    return () => cancelAnimationFrame(frame);
  }, [p.focusRequest, reveal]);

  function onFocus(e: FocusEvent<HTMLDivElement>) {
    const el = e.target as HTMLElement; // the item focused inside the canvas, not the canvas itself
    const id = el.dataset.item;
    if (!id) return;
    p.onFocusItem(id);
    reveal(el);
  }

  return (
    <div ref={container} role="group" aria-label="Workflow steps" onKeyDown={p.onKeyDown} onFocus={onFocus} className="relative min-h-0 min-w-0 flex-1">
      <ReactFlow
        nodes={nodes}
        edges={built.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, __, dragged) => p.onMove(new Map(dragged.map((n) => [n.id, n.position])))}
        onConnect={(c) => {
          if (c.source && c.source !== START && c.sourceHandle && c.target) p.onConnect({ node: c.source, port: c.sourceHandle }, c.target);
        }}
        nodesDraggable={p.editable}
        nodesConnectable={p.editable}
        elementsSelectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        disableKeyboardA11y
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        panActivationKeyCode={null}
        zoomActivationKeyCode={null}
        zoomOnDoubleClick={false}
        minZoom={0.25}
        maxZoom={1.5}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <MiniMap pannable zoomable ariaLabel="Overview of the steps" nodeClassName="canvas-minimap-node" />
      </ReactFlow>
      <div className="absolute bottom-4 left-4 flex items-center gap-1.5">
        {p.editable && (
          <Button size="md" onClick={p.onLayout}>
            Auto layout
          </Button>
        )}
        <Button size="md" aria-label="Zoom in" onClick={() => void flow.zoomIn({ duration: 0 })}>＋</Button>
        <Button size="md" aria-label="Zoom out" onClick={() => void flow.zoomOut({ duration: 0 })}>−</Button>
        <Button size="md" onClick={() => void flow.fitView({ padding: 0.2, maxZoom: 1, duration: 0 })}>Fit</Button>
        <span className="ml-1.5 font-mono text-small text-muted">{Math.round(zoom * 100)}%</span>
      </div>
    </div>
  );
}

export function Canvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
