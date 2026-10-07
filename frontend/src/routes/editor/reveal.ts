// SPDX-License-Identifier: Apache-2.0
/** Whether the canvas moves its view to the item focus landed on (ledger M13, revised at the final checkpoint). */

export type Rect = { left: number; top: number; right: number; bottom: number };

const overlap = (a: Rect, b: Rect): Rect | null => {
  const r = { left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) };
  return r.left < r.right && r.top < r.bottom ? r : null;
};
const contains = (outer: Rect, inner: Rect) =>
  outer.left <= inner.left && outer.top <= inner.top && inner.right <= outer.right && inner.bottom <= outer.bottom;

/** When the keyboard moved focus (`keyboard`), the view moves unless the item is wholly in the clear: inside the canvas
 * and under nothing laid over it (the minimap, its controls, the placing bar). When anything else did (a pointer's
 * press on the item, or the editor after a press elsewhere: "Go to", a step added or placed, a version viewed), it
 * moves only when the item is entirely hidden (WCAG 2.4.11): an item that shows at all stays where it is, so nothing
 * slides from under a press, or a step placed with a click from under the click. */
export function mustReveal(item: Rect, canvas: Rect, over: Rect[], keyboard: boolean): boolean {
  if (keyboard) return !contains(canvas, item) || over.some((o) => overlap(item, o) !== null);
  const shown = overlap(item, canvas);
  return shown === null || over.some((o) => contains(o, shown));
}
