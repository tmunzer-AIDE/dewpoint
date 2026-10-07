// SPDX-License-Identifier: Apache-2.0
// A step on the canvas (1c, its tells stripped: outline §6). No tinted icon tile: the type's mono code; the step
// whose panel is open has a 2 px outline, never a halo; an unknown type draws dashed and says so.
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Fragment } from "react";
import type { PortRef } from "../../lib/graph";
import type { GraphNode, NodeType } from "../../lib/workflows";
import { item, say, type ItemAction } from "./items";

const CODES: Record<string, string> = {
  "flow.if": "IF", "flow.switch": "SWITCH", "flow.loop": "LOOP", "flow.filter": "FILTER", "flow.set_variables": "SET",
  "flow.delay": "DELAY", "flow.wait_until": "WAIT", "flow.stop": "STOP", "flow.fail": "FAIL", "flow.run_workflow": "FLOW",
  "flow.transform": "MAP",
};  // prettier-ignore

/** A control step's code says what it does; an action's names its plugin. */
export function typeCode(ref: string): string {
  const type = ref.split("@")[0] ?? ref;
  return CODES[type] ?? (type.split(".")[0] ?? "").toUpperCase().slice(0, 6);
}

export type Problems = { errors: number; warnings: number };
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function StepCardBody({
  node, type, problems, separate, current, tabIndex, onOpen,
}: {
  node: GraphNode; type: NodeType | undefined; problems: Problems; separate: number; current: boolean; tabIndex: number;
  onOpen: () => void;
}) {  // prettier-ignore
  const title = type ? type.title : `Unknown step type ${node.type}`;
  const said = [
    node.key,
    title,
    problems.errors ? plural(problems.errors, "problem", "problems") : null,
    !problems.errors && problems.warnings ? plural(problems.warnings, "warning", "warnings") : null,
    separate ? `${plural(separate, "expression runs", "expressions run")} as a separate step` : null,
  ].filter(Boolean);
  // The open step wears a 2 px accent border all round (1c), its padding a pixel less so nothing moves; the focus ring
  // stays the one 2 px outline (theme.css), so an open step never looks focused when it isn't.
  const border = current ? "border-2 border-accent px-[13px]" : "border border-line-strong px-3.5";
  return (
    <button
      type="button"
      data-item={item.node(node.id)}
      tabIndex={tabIndex}
      aria-label={said.join(", ")}
      onClick={onOpen}
      className={`pointer-events-auto flex h-[64px] w-[260px] items-center gap-3 rounded-lg bg-surface text-left shadow-node ${border} ${type ? "" : "border-dashed"}`}
    >
      <span aria-hidden="true" className="w-12 shrink-0 truncate font-mono text-meta font-semibold text-accent-ink">{typeCode(node.type)}</span>
      <span className="min-w-0 flex-1" aria-hidden="true">
        <span className="block truncate text-body font-semibold">{node.key}</span>
        <span className={`block truncate text-small ${type ? "text-muted" : "text-warn-ink"}`}>{title}</span>
      </span>
      {(problems.errors > 0 || problems.warnings > 0) && (
        <span
          aria-hidden="true"
          className={`shrink-0 rounded-sm border px-1.5 font-mono text-meta ${problems.errors ? "border-danger text-danger" : "border-warn-line bg-warn-bg text-warn-ink"}`}
        >
          {problems.errors || problems.warnings}
        </span>
      )}
    </button>
  );
}

export type StepData = {
  node: GraphNode;
  type: NodeType | undefined;
  ports: string[];
  connected: string[];
  problems: Problems;
  separate: number;
  current: boolean;
  focusId: string;
  editable: boolean;
  onItem: (action: ItemAction) => void;
};

// React Flow turns a node's pointer events off when it can be neither selected nor dragged (ledger M11): its
// controls take them back, as an edge's "+" does in the label layer. The canvas draws in px, as React Flow lays it
// out (the UI's rem is 14 px): a card is CARD in size, a "+" 24 square, 24 below its card (pluses.ts counts on it).
const PLUS = "nodrag nopan pointer-events-auto absolute top-full mt-[24px] grid size-[24px] -translate-x-1/2 place-items-center rounded-sm border border-line-strong bg-surface text-body text-muted hover:bg-surface-hover";

/** The React Flow node: the card, its input on top, a handle per port at the bottom (and one for an edge from a
 * port the type no longer has), each port named when it isn't the only `out`, and a "+" under each free port. */
export function StepNode({ data }: NodeProps<Node<StepData, "step">>) {
  const { node, ports, connected, editable } = data;
  const named = ports.length > 1 || (ports[0] !== undefined && ports[0] !== "out");
  const extra = connected.filter((p) => !ports.includes(p));
  const at = (i: number) => `${((i + 1) / (ports.length + 1)) * 100}%`;
  return (
    <div className="relative">
      <Handle type="target" position={Position.Top} isConnectable={editable} />
      <StepCardBody
        node={node}
        type={data.type}
        problems={data.problems}
        separate={data.separate}
        current={data.current}
        tabIndex={data.focusId === item.node(node.id) ? 0 : -1}
        onOpen={() => data.onItem({ kind: "open", node: node.id })}
      />
      {ports.map((port, i) => {
        const from: PortRef = { node: node.id, port };
        const id = item.port(node.id, port);
        return (
          <Fragment key={port}>
            <Handle type="source" id={port} position={Position.Bottom} isConnectable={editable} style={{ left: at(i) }} />
            {named && (
              <span aria-hidden="true" className="pointer-events-none absolute top-full mt-1 -translate-x-1/2 font-mono text-meta text-muted" style={{ left: at(i) }}>
                {port}
              </span>
            )}
            {editable && !connected.includes(port) && (
              <button
                type="button"
                data-item={id}
                tabIndex={data.focusId === id ? 0 : -1}
                aria-label={say.after(node.key, port)}
                onClick={() => data.onItem({ kind: "after", from })}
                className={PLUS}
                style={{ left: at(i) }}
              >
                ＋
              </button>
            )}
          </Fragment>
        );
      })}
      {extra.map((port) => (
        <Handle key={port} type="source" id={port} position={Position.Bottom} isConnectable={false} className="opacity-0" />
      ))}
    </div>
  );
}
