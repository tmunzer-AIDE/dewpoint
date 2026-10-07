// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { CARD } from "../../lib/layout";
import { route } from "./FlowEdge";
import { PLUS } from "./pluses";

it("draws an edge going down as React Flow does, its middle halfway", () => {
  expect(route({ sourceX: 100, sourceY: 204, targetX: 100, targetY: 280 })).toEqual({});
});

it("loops an edge that climbs (a cycle's way back, a self edge) round the right of both cards", () => {
  // b (below) back to a (above), one over the other: drawn straight, it would run behind both cards, its "+" on the
  // forward edge's (the owner's review of milestone 3).
  const back = route({ sourceX: 100, sourceY: 344, targetX: 100, targetY: 140 });
  expect(back.centerX).toBeGreaterThanOrEqual(100 + CARD.width / 2 + 24);
  const self = route({ sourceX: 100, sourceY: 204, targetX: 100, targetY: 140 });
  expect(self.centerX).toBe(back.centerX);
  expect(route({ sourceX: 400, sourceY: 344, targetX: 100, targetY: 140 }).centerX).toBe(back.centerX! + 300);
});

it("runs each port's climbing edge in its own lane, so a join from two ports climbs as two lines", () => {
  // if's true and false both lead to j, above and to the right (the owner's review of 6d7766e): one lane each.
  const at = { sourceY: 364, targetX: 470, targetY: 0 };
  const first = route({ ...at, sourceX: 86 }, 0).centerX!;
  const second = route({ ...at, sourceX: 173 }, 1).centerX!;
  expect(second - first).toBeGreaterThanOrEqual(PLUS + 8); // their "+" sit apart at their labels
  expect(route({ sourceX: 100, sourceY: 204, targetX: 100, targetY: 280 }, 1)).toEqual({}); // going down: React Flow's
});

it("climbs clear of the source card's right edge, whichever of its ports the edge leaves from", () => {
  // A step at x 0 with five ports: its first sits at a sixth of the card. Climbing to a step above and to the left,
  // the lane measured from the port would run through the card (the final checkpoint's second review).
  const first = 1 / 6;
  const climb = route({ sourceX: CARD.width * first, sourceY: 364, targetX: -300, targetY: 0 }, 0, first);
  expect(climb.centerX).toBeGreaterThanOrEqual(CARD.width + 24);
  // A one-port step (its port in the middle) climbs where it always has.
  expect(route({ sourceX: 130, sourceY: 364, targetX: -300, targetY: 0 }, 0, 0.5).centerX).toBe(130 + CARD.width / 2 + 40);
});
