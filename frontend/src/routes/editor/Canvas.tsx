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
import {
  START, drawableEdges, entries, idKey, nodesOf, portOf, portsOf, pos, sameId, startPosition, type PortRef,
} from "../../lib/graph";  // prettier-ignore
import { CARD, MIN_ZOOM } from "../../lib/layout";
import type { GraphDoc, GraphEdge, NodeType } from "../../lib/workflows";
import { FlowEdge, type FlowData } from "./FlowEdge";
import { item, say, type ItemAction } from "./items";
import { StartNode, type StartData } from "./StartCard";
import { StepNode, type Problems, type StepData } from "./StepCard";
import { PLUS, Pluses, placePluses, type Box, type Point } from "./pluses";
import { mustReveal } from "./reveal";

const nodeTypes = { step: StepNode, start: StartNode } satisfies NodeTypes;
const edgeTypes = { flow: FlowEdge } satisfies EdgeTypes;
const NONE: Problems = { errors: 0, warnings: 0 };
// Every card's size before React Flow measures it: a node without one is hidden until measured, so a step just added
// couldn't take focus (ledger M11).
const SIZE = { initialWidth: CARD.width, initialHeight: CARD.height };

export interface CanvasProps {
  doc: GraphDoc;
  types: Map<string, NodeType>;
  problems: Map<string, Problems>; // by step id's identity (`idKey`): the server's canonical ids
  separate: Map<string, number>; // by step id's identity
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
  placing: boolean; // the next click on an empty place puts a step there (WCAG 2.5.7)
  overview: boolean; // the minimap: off while a side panel narrows the canvas (the owner's ruling on milestone 3)
  onPlace: (at: { x: number; y: number }) => void; // the click, in the canvas's own coordinates
}

/** What React Flow draws: the start card, each step, an edge from the start card to each entry step, and each edge
 * whose ends exist, once (`drawableEdges`: an imported draft may hold others, which the problems name). */
function build(p: CanvasProps): { nodes: Node[]; edges: Edge[] } {
  // React Flow's ids are the steps' identities (`idKey`): an edge may spell its ends otherwise than the steps do.
  const used = new Map<string, string[]>();
  for (const e of drawableEdges(p.doc)) used.set(idKey(e.from.node), [...(used.get(idKey(e.from.node)) ?? []), portOf(e)]);
  const keyOf = new Map(nodesOf(p.doc).map((n) => [idKey(n.id), n.key]));
  const start: StartData = { empty: nodesOf(p.doc).length === 0, focusId: p.focusId, editable: p.editable, onItem: p.onItem };
  const nodes: Node[] = [
    { id: START, type: "start", position: startPosition(p.doc), draggable: false, selectable: false, data: start, ...SIZE },
    ...nodesOf(p.doc).map((n): Node => {
      const type = p.types.get(n.type);
      const data: StepData = {
        node: n, type, ports: portsOf(n, type), connected: used.get(idKey(n.id)) ?? [], problems: p.problems.get(idKey(n.id)) ?? NONE,
        separate: p.separate.get(idKey(n.id)) ?? 0, current: p.current !== null && sameId(p.current, n.id), focusId: p.focusId,
        editable: p.editable,
        onItem: p.onItem,
      };  // prettier-ignore
      return { id: idKey(n.id), type: "step", position: pos(n), draggable: p.editable, selectable: false, data, ...SIZE };
    }),
  ];
  const flow = (id: string, label: string, action: ItemAction, lane = 0): FlowData => ({ item: id, label, action, focusId: p.focusId, editable: p.editable, lane, onItem: p.onItem });
  const laneOf = (e: GraphEdge) => {
    const n = nodesOf(p.doc).find((m) => idKey(m.id) === idKey(e.from.node));
    return n ? Math.max(0, portsOf(n, p.types.get(n.type)).indexOf(portOf(e))) : 0;
  };
  const edges: Edge[] = [
    ...entries(p.doc).map((n): Edge => ({
      id: item.entry(n.id), source: START, sourceHandle: "out", target: idKey(n.id), type: "flow",
      data: flow(item.entry(n.id), say.before(n.key), { kind: "before", entry: n.id }),
    })),
    ...drawableEdges(p.doc).map((e): Edge => ({
      id: item.edge(e), source: idKey(e.from.node), sourceHandle: portOf(e), target: idKey(e.to.node), type: "flow",
      // Named by its port when it isn't `out`: two edges from one step to the same one (a branch's join) read apart.
      data: flow(item.edge(e), say.insert(keyOf.get(idKey(e.from.node)) ?? "a step", portOf(e), keyOf.get(idKey(e.to.node)) ?? "a step"), { kind: "insert", edge: e }, laneOf(e)),
    })),
  ];  // prettier-ignore
  return { nodes, edges };
}

/** What a "+" keeps off (pluses.ts): every card as drawn, and each "+" a card has under a free port, or the start
 * card's before the first step: where StepCard and StartCard put them, 24 below the card. */
function obstacles(nodes: Node[]): Box[] {
  const boxes: Box[] = [];
  const plus = (c: Point): Box => ({ left: c.x - PLUS / 2, top: c.y - PLUS / 2, right: c.x + PLUS / 2, bottom: c.y + PLUS / 2 });
  for (const n of nodes) {
    const w = n.measured?.width ?? CARD.width;
    const h = n.measured?.height ?? CARD.height;
    const { x, y } = n.position;
    boxes.push({ left: x, top: y, right: x + w, bottom: y + h });
    const below = y + h + 24 + PLUS / 2;
    if (n.type === "step") {
      const d = n.data as StepData;
      if (d.editable)
        d.ports.forEach((port, i) => {
          if (!d.connected.includes(port)) boxes.push(plus({ x: x + (w * (i + 1)) / (d.ports.length + 1), y: below }));
        });
    } else if ((n.data as StartData).empty && (n.data as StartData).editable) boxes.push(plus({ x: x + w / 2, y: below }));
  }
  return boxes;
}

function Flow(p: CanvasProps) {
  const flow = useReactFlow();
  const { zoom } = useViewport();
  const container = useRef<HTMLDivElement>(null);
  const built = useMemo(() => build(p), [p]);
  const [nodes, setNodes] = useState(built.nodes);
  // Every "+" placed at once, from the line each edge reports and the cards as drawn (pluses.ts).
  const [lines, setLines] = useState(() => new Map<string, { label: Point; points: Point[] }>());
  const report = useCallback(
    (id: string, label: Point, points: Point[]) =>
      setLines((drawn) => {
        const was = drawn.get(id);
        if (was && was.label.x === label.x && was.label.y === label.y && JSON.stringify(was.points) === JSON.stringify(points)) return drawn;
        return new Map(drawn).set(id, { label, points });
      }),
    [],
  );
  const forget = useCallback(
    (id: string) =>
      setLines((drawn) => {
        if (!drawn.has(id)) return drawn;
        const rest = new Map(drawn);
        rest.delete(id);
        return rest;
      }),
    [],
  );
  const cards = useMemo(() => obstacles(nodes), [nodes]);
  const placed = useMemo(() => placePluses([...lines].map(([id, line]) => ({ id, ...line })), cards), [lines, cards]);
  const pluses = useMemo(() => ({ report, forget, placed }), [report, forget, placed]);
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

  /** Brings the item focus landed on into view, keeping the zoom, when `mustReveal` says so: for the keyboard unless
   * it's wholly in the clear; otherwise only when it's entirely hidden, so a pointer's press never slides it away
   * (ledger M13, revised at the final checkpoint). */
  const reveal = useCallback(
    (el: HTMLElement) => {
      const frame = container.current;
      const box = frame?.getBoundingClientRect();
      if (!frame || !box) return;
      const r = el.getBoundingClientRect();
      // What lies over the canvas (the minimap, its controls, the placing bar) hides what's under it as surely as its
      // edge does (WCAG 2.4.11).
      const over = [...(frame.parentElement ?? frame).querySelectorAll<HTMLElement>(".react-flow__minimap, [data-canvas-overlay]")]
        .map((o) => o.getBoundingClientRect())
        .filter((o) => o.width > 0 && o.height > 0);
      if (!mustReveal(r, box, over, el.matches(":focus-visible"))) return;
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
    <div ref={container} role="group" aria-label="Workflow steps" onKeyDown={p.onKeyDown} onFocus={onFocus} className="canvas-frame relative min-h-0 min-w-0 flex-1">
      <Pluses.Provider value={pluses}>
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
          minZoom={MIN_ZOOM}
          maxZoom={1.5}
          fitView
          fitViewOptions={{ padding: 0.2, minZoom: MIN_ZOOM, maxZoom: 1 }}
          proOptions={{ hideAttribution: true }}
          onPaneClick={(e) => {
            if (p.placing) p.onPlace(flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
          }}
          className={p.placing ? "canvas-placing" : undefined}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          {p.overview && <MiniMap pannable zoomable ariaLabel="Overview of the steps" nodeClassName="canvas-minimap-node" />}
        </ReactFlow>
      </Pluses.Provider>
      <div data-canvas-overlay className="absolute bottom-4 left-4 flex items-center gap-1.5">
        {p.editable && (
          <Button size="md" onClick={p.onLayout}>
            Auto layout
          </Button>
        )}
        <Button size="md" aria-label="Zoom in" onClick={() => void flow.zoomIn({ duration: 0 })}>＋</Button>
        <Button size="md" aria-label="Zoom out" onClick={() => void flow.zoomOut({ duration: 0 })}>−</Button>
        <Button size="md" onClick={() => void flow.fitView({ padding: 0.2, minZoom: MIN_ZOOM, maxZoom: 1, duration: 0 })}>Fit</Button>
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
