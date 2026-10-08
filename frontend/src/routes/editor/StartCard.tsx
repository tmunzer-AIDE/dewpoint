// SPDX-License-Identifier: Apache-2.0
// The start card (4b ruling 2): not a graph node. It stands for whatever starts a run; its edges reach every entry
// step, and, before any step exists, its "+" adds the first one.
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { START } from "../../lib/graph";
import { item, type ItemAction } from "./items";

export type StartData = { empty: boolean; focusId: string; editable: boolean; onItem: (action: ItemAction) => void };

export function StartNode({ data }: NodeProps<Node<StartData, "start">>) {
  const first = item.port(START, "out");
  return (
    <div className="relative">
      <button
        type="button"
        data-item={item.start}
        tabIndex={data.focusId === item.start ? 0 : -1}
        aria-label={data.editable ? "Start, where every run begins. Add a step that runs first" : "Start, where every run begins"}
        onClick={() => data.editable && data.onItem({ kind: "after", from: null })}
        className="pointer-events-auto flex h-[64px] w-[260px] flex-col justify-center rounded-lg border border-dashed border-line-strong bg-surface px-3.5 text-left"
      >
        <span className="truncate text-body font-semibold">Start</span>
        <span className="truncate text-small text-muted">By hand, a schedule or a webhook</span>
      </button>
      <Handle type="source" id="out" position={Position.Bottom} isConnectable={false} />
      {data.empty && data.editable && (
        <button
          type="button"
          data-item={first}
          tabIndex={data.focusId === first ? 0 : -1}
          aria-label="Add the first step"
          onClick={() => data.onItem({ kind: "after", from: null })}
          className="nodrag nopan pointer-events-auto absolute top-full left-1/2 mt-[24px] grid size-[24px] -translate-x-1/2 place-items-center rounded-sm border border-line-strong bg-surface text-body text-muted hover:bg-surface-hover"
        >
          ＋
        </button>
      )}
    </div>
  );
}
