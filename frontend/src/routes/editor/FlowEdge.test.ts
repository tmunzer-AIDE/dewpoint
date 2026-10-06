// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { CARD } from "../../lib/layout";
import { route } from "./FlowEdge";

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
