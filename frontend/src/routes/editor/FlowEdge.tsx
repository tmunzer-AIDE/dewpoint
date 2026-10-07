// SPDX-License-Identifier: Apache-2.0
// An edge: a stepped line, and, when the draft is editable, a "+" at its middle to insert a step there (a 24 px
// square with a 4 px radius: no circles, outline §6).
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import { useContext, useLayoutEffect } from "react";
import { CARD } from "../../lib/layout";
import type { ItemAction } from "./items";
import { PLUS, Pluses, pointsOf } from "./pluses";

/** Where an edge's middle runs. Going down, React Flow's own: halfway. One that climbs (a cycle's way back, a self
 * edge, a step beside its source) runs its middle past the right of both cards: drawn straight it would pass behind
 * them, and its "+" would sit on the forward edge's, out of a pointer's reach (the owner's review of milestone 3).
 * Each port climbs in its own lane (`lane`: the port's place among its step's), a "+" and its clearance apart, so a
 * join from two ports climbs as two lines (the owner's review of 6d7766e). */
export function route(e: { sourceX: number; sourceY: number; targetX: number; targetY: number }, lane = 0): { centerX?: number } {
  return e.targetY < e.sourceY ? { centerX: Math.max(e.sourceX, e.targetX) + CARD.width / 2 + 40 + lane * (PLUS + 8) } : {};
}

export type FlowData = {
  item: string; label: string; action: ItemAction; focusId: string; editable: boolean; lane: number;
  onItem: (action: ItemAction) => void;
};  // prettier-ignore

export function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<Edge<FlowData, "flow">>) {
  const [path, x, y] = getSmoothStepPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, borderRadius: 6,
    ...route({ sourceX, sourceY, targetX, targetY }, data?.lane ?? 0),
  });  // prettier-ignore
  // The line drawn goes to the canvas, which places every "+" so none shares another's rectangle (pluses.ts).
  const { report, forget, placed } = useContext(Pluses);
  useLayoutEffect(() => report(id, { x, y }, pointsOf(path)), [id, path, x, y, report]);
  useLayoutEffect(() => () => forget(id), [id, forget]);
  const at = placed.get(id) ?? { x, y };
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
            className="nodrag nopan pointer-events-auto absolute grid size-[24px] place-items-center rounded-sm border border-line-strong bg-surface text-body text-muted hover:bg-surface-hover"
            style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
          >
            ＋
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
