// SPDX-License-Identifier: Apache-2.0
import { getViewportForBounds, type Rect } from "@xyflow/react";
import { describe, expect, it } from "vitest";
import { MIN_ZOOM } from "../../lib/layout";
import { FIT, fitted } from "./fit";

const box = (x: number, y: number, width: number, height: number): Rect => ({ x, y, width, height });
const START = box(0, 0, 260, 64); // the start card, 260 by 64, its row at y = 0
/** Where a card lands on the canvas under a view: its edges in the canvas's own pixels. */
const onScreen = (card: Rect, v: { x: number; y: number; zoom: number }) => ({
  left: card.x * v.zoom + v.x, top: card.y * v.zoom + v.y, right: (card.x + card.width) * v.zoom + v.x, bottom: (card.y + card.height) * v.zoom + v.y,
});  // prettier-ignore

describe("the view Fit gives", () => {
  it("is React Flow's own for a graph that fits: the whole graph, centred, padded", () => {
    const graph = box(-200, 0, 660, 484);
    const canvas = { width: 1100, height: 700 };
    expect(fitted(graph, START, canvas)).toEqual(getViewportForBounds(graph, canvas.width, canvas.height, MIN_ZOOM, FIT.maxZoom, FIT.padding));
  });

  it("keeps the start card in the clear when even the farthest zoom can't fit the graph: a run's page at 320 px", () => {
    // The runs-check workflow (greet, check, then done or halt) on the 260 by 161 canvas a run's page leaves at 320 px:
    // centred, the graph lost its top 16 px, and the start card's middle lay under the banner.
    const v = fitted(box(-200, 0, 660, 484), START, { width: 260, height: 161 });
    expect(v.zoom).toBe(MIN_ZOOM);
    const card = onScreen(START, v);
    expect(card.top).toBeGreaterThanOrEqual(13); // the margin Fit gives a graph on a canvas 161 tall
    expect(card.bottom).toBeLessThanOrEqual(161);
    expect(card.left).toBeGreaterThanOrEqual(0);
    expect(card.right).toBeLessThanOrEqual(260);
  });

  it("moves the view the least it must: sideways only for a start card off to one side of a graph too wide", () => {
    const graph = box(0, 0, 2000, 204); // steps far to the start card's right
    const centred = getViewportForBounds(graph, 400, 600, MIN_ZOOM, FIT.maxZoom, FIT.padding);
    const v = fitted(graph, START, { width: 400, height: 600 });
    expect(v.y).toBe(centred.y);
    expect(onScreen(START, v).left).toBeCloseTo(33); // the margin Fit gives a graph on a canvas 400 wide
  });

  it("shows the start card's top on a canvas too short for all of it", () => {
    const v = fitted(box(-200, 0, 660, 484), START, { width: 260, height: 20 });
    expect(onScreen(START, v).top).toBeCloseTo(1);
  });
});
