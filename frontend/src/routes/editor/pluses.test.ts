// SPDX-License-Identifier: Apache-2.0
import { Position, getSmoothStepPath } from "@xyflow/react";
import { describe, expect, it } from "vitest";
import { PLUS, placePluses, pointsOf, type Box, type Point } from "./pluses";

/** Whether two "+" squares, centred on `a` and `b`, overlap. */
const overlap = (a: Point, b: Point) => Math.abs(a.x - b.x) < PLUS && Math.abs(a.y - b.y) < PLUS;
/** Whether `p` lies on the polyline (within half a unit). */
function onLine(p: Point, line: Point[]): boolean {
  return line.slice(1).some((b, i) => {
    const a = line[i]!;
    const within = (v: number, x: number, y: number) => v >= Math.min(x, y) - 0.5 && v <= Math.max(x, y) + 0.5;
    const cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
    return within(p.x, a.x, b.x) && within(p.y, a.y, b.y) && Math.abs(cross) <= 0.5 * Math.hypot(b.x - a.x, b.y - a.y);
  });
}
const edge = (id: string, points: Point[], label: Point) => ({ id, points, label });
const down = (x: number) => [{ x, y: 0 }, { x, y: 200 }];

describe("where each edge's + goes", () => {
  it("reads React Flow's stepped path as the line it draws, end to end", () => {
    const [path] = getSmoothStepPath({ sourceX: 10, sourceY: 20, sourcePosition: Position.Bottom, targetX: 300, targetY: -200, targetPosition: Position.Top, borderRadius: 6 });
    const line = pointsOf(path);
    expect(line[0]).toEqual({ x: 10, y: 20 });
    expect(line.at(-1)).toEqual({ x: 300, y: -200 });
  });

  it("keeps each + where React Flow puts its label when nothing is in the way", () => {
    const placed = placePluses([edge("a", down(0), { x: 0, y: 100 }), edge("b", down(300), { x: 300, y: 100 })], []);
    expect(placed.get("a")).toEqual({ x: 0, y: 100 });
    expect(placed.get("b")).toEqual({ x: 300, y: 100 });
  });

  it("moves the second of two + that would share a rectangle along its own edge", () => {
    // A join climbing to a step above: both edges run up one side, and React Flow labels both at one point.
    const t = [{ x: 86, y: 364 }, { x: 86, y: 384 }, { x: 600, y: 384 }, { x: 600, y: -20 }, { x: 470, y: -20 }, { x: 470, y: 0 }];
    const f = [{ x: 173, y: 364 }, { x: 173, y: 384 }, { x: 600, y: 384 }, { x: 600, y: -20 }, { x: 470, y: -20 }, { x: 470, y: 0 }];
    const placed = placePluses([edge("t", t, { x: 600, y: 182 }), edge("f", f, { x: 600, y: 182 })], []);
    expect(overlap(placed.get("t")!, placed.get("f")!)).toBe(false);
    expect(onLine(placed.get("t")!, t) && onLine(placed.get("f")!, f)).toBe(true);
  });

  it("keeps a + off a card when its edge has room elsewhere", () => {
    const card: Box = { left: -130, top: 80, right: 130, bottom: 144 }; // a step dragged over the edge's middle
    const placed = placePluses([edge("a", down(0), { x: 0, y: 100 })], [card]).get("a")!;
    expect(onLine(placed, down(0))).toBe(true);
    expect(placed.y + PLUS / 2 <= card.top || placed.y - PLUS / 2 >= card.bottom).toBe(true);
  });

  it("never puts an edge's + on a port's or the start card's own +, even where the cards leave it no room", () => {
    // Cards over the whole edge: no point along it is off them, so only the "+" already drawn can rule one out.
    const cards: Box[] = [{ left: -200, top: -50, right: 200, bottom: 250 }];
    const ports: Box[] = [100, 90, 110].map((y) => ({ left: -PLUS / 2, top: y - PLUS / 2, right: PLUS / 2, bottom: y + PLUS / 2 }));
    const placed = placePluses([edge("a", down(0), { x: 0, y: 100 })], cards, ports).get("a")!;
    for (const port of ports) expect(overlap(placed, { x: (port.left + port.right) / 2, y: (port.top + port.bottom) / 2 })).toBe(false);
  });

  it("never stacks two + however the steps are placed, even when every edge is one line", () => {
    const same = Array.from({ length: 6 }, (_, i) => edge(`e${i}`, down(0), { x: 0, y: 100 }));
    const placed = [...placePluses(same, []).values()];
    expect(placed).toHaveLength(6);
    for (const [i, a] of placed.entries()) for (const b of placed.slice(i + 1)) expect(overlap(a, b)).toBe(false);
  });
});
