// SPDX-License-Identifier: Apache-2.0
// An edge: a stepped line, and, when the draft is editable, a "+" at its middle to insert a step there (a 24 px
// square with a 4 px radius: no circles, outline §6).
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import type { ItemAction } from "./items";

export type FlowData = { item: string; label: string; action: ItemAction; focusId: string; editable: boolean; onItem: (action: ItemAction) => void };

export function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<Edge<FlowData, "flow">>) {
  const [path, x, y] = getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, borderRadius: 6 });
  return (
    <>
      <BaseEdge id={id} path={path} />
      {data?.editable && (
        <EdgeLabelRenderer>
          <button
            type="button"
            data-item={data.item}
            tabIndex={data.focusId === data.item ? 0 : -1}
            aria-label={data.label}
            onClick={() => data.onItem(data.action)}
            className="nodrag nopan pointer-events-auto absolute grid size-6 place-items-center rounded-sm border border-line-strong bg-surface text-body text-muted hover:bg-surface-hover"
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
          >
            ＋
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
