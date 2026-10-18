// SPDX-License-Identifier: Apache-2.0
/** The view the canvas opens on, and its Fit button gives: React Flow's fit, the whole graph centred and padded at the
 * zoom that holds it, between the farthest zoom and 100 %. A graph too big for the canvas even at the farthest zoom
 * would be centred, cut at both ends, its start card behind what's above the canvas (a run's page at 320 px, under its
 * banner): the view then moves the least it must to keep the start card in the clear, its top and left first. */
import { getViewportForBounds, type Rect, type Viewport } from "@xyflow/react";
import { MIN_ZOOM } from "../../lib/layout";

export const FIT = { padding: 0.2, minZoom: MIN_ZOOM, maxZoom: 1 };

/** How far a card's edge at `at`, `size` long, moves to lie in the clear on a canvas `extent` long: inside the margin
 * Fit gives a graph (React Flow's own padding, `parsePadding`), its leading edge when it can't all be. */
function inClear(at: number, size: number, extent: number): number {
  const margin = Math.floor((extent - extent / (1 + FIT.padding)) / 2);
  if (at < margin) return margin - at;
  const over = at + size - (extent - margin);
  return over > 0 ? -Math.min(over, at - margin) : 0;
}

/** The view that fits `graph` on a canvas `canvas` big, keeping `start` (the start card), in the canvas's coordinates,
 * in the clear. */
export function fitted(graph: Rect, start: Rect, canvas: { width: number; height: number }): Viewport {
  const v = getViewportForBounds(graph, canvas.width, canvas.height, FIT.minZoom, FIT.maxZoom, FIT.padding);
  return {
    x: v.x + inClear(start.x * v.zoom + v.x, start.width * v.zoom, canvas.width),
    y: v.y + inClear(start.y * v.zoom + v.y, start.height * v.zoom, canvas.height),
    zoom: v.zoom,
  };
}
