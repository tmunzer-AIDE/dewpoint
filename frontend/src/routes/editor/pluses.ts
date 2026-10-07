// SPDX-License-Identifier: Apache-2.0
import { createContext } from "react";

/** Where each edge's "+" sits (the owner's review of 6d7766e): never on another's rectangle, however the steps are
 * placed, and off the cards where its edge leaves room. All in the canvas's own units, where a "+" is 24 square. */

export type Point = { x: number; y: number };
export type Box = { left: number; top: number; right: number; bottom: number };

export const PLUS = 24; // a "+" is 24 by 24 (size-6) at 100%
const CLEAR = 8; // between two "+", and between a "+" and a card

/** The line React Flow's stepped path draws, as its points: `M x y`, `L x,y`, and each bend's `Q` (its corner, then
 * where it ends), so the corners are cut no closer than the bend's radius. */
export function pointsOf(path: string): Point[] {
  const n = (path.match(/-?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi) ?? []).map(Number);
  const out: Point[] = [];
  for (let i = 0; i + 1 < n.length; i += 2) out.push({ x: n[i]!, y: n[i + 1]! });
  return out;
}

/** The point a fraction `t` of the way along the line. */
function along(line: Point[], t: number): Point {
  const lengths = line.slice(1).map((b, i) => Math.hypot(b.x - line[i]!.x, b.y - line[i]!.y));
  let rest = t * lengths.reduce((a, b) => a + b, 0);
  for (const [i, length] of lengths.entries()) {
    if (rest <= length && length > 0) {
      const a = line[i]!, b = line[i + 1]!;  // prettier-ignore
      return { x: a.x + ((b.x - a.x) * rest) / length, y: a.y + ((b.y - a.y) * rest) / length };
    }
    rest -= length;
  }
  return line.at(-1) ?? { x: 0, y: 0 };
}

const square = (p: Point, pad: number): Box => ({
  left: p.x - PLUS / 2 - pad, top: p.y - PLUS / 2 - pad, right: p.x + PLUS / 2 + pad, bottom: p.y + PLUS / 2 + pad,
});  // prettier-ignore
const hit = (a: Box, b: Box) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

// From the middle out: the label's own point first, then ever further along the edge either way.
const FRACTIONS = Array.from({ length: 9 }, (_, i) => [0.5 - (i + 1) * 0.05, 0.5 + (i + 1) * 0.05]).flat();

/** Each edge's "+", in a stable order (by id): React Flow's label point when it's clear, else the clear point along
 * the edge nearest its middle; off the cards (`cards`) when the edge has room, and never on a "+" already placed.
 * When nothing along the edge is clear of the others (edges drawn as one line), it steps sideways from the label until
 * it is: two "+" never share a rectangle, so a pointer always reaches the one it aims at. */
export function placePluses(edges: { id: string; label: Point; points: Point[] }[], cards: Box[]): Map<string, Point> {
  const placed = new Map<string, Point>();
  const taken: Box[] = [];
  const free = (p: Point) => !taken.some((b) => hit(square(p, CLEAR / 2), b));
  const offCards = (p: Point) => !cards.some((c) => hit(square(p, CLEAR), c));
  for (const e of [...edges].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
    const candidates = [e.label, ...(e.points.length > 1 ? FRACTIONS.map((t) => along(e.points, t)) : [])];
    let at = candidates.find((p) => free(p) && offCards(p)) ?? candidates.find(free);
    for (let k = 1; at === undefined; k++) {
      const p = { x: e.label.x + k * (PLUS + CLEAR), y: e.label.y };
      if (free(p)) at = p;
    }
    placed.set(e.id, at);
    taken.push(square(at, CLEAR / 2));
  }
  return placed;
}

/** The canvas's placement, shared with its edges: each reports the line it draws and draws its "+" where placed. */
export const Pluses = createContext<{
  report: (id: string, label: Point, points: Point[]) => void;
  forget: (id: string) => void;
  placed: Map<string, Point>;
}>({ report: () => undefined, forget: () => undefined, placed: new Map() });
