// SPDX-License-Identifier: Apache-2.0
// Auto layout, on demand (outline §2): dagre, top to bottom. Every card, the start card included, is 260 by 64, and
// rows are 76 apart, so one row is ROW (140) from the next and the start card's row sits at y = 0.
import dagre, { type NodeLabel } from "@dagrejs/dagre";
import { START, edgesOf, entries, idKey, nodesOf } from "./graph";
import type { GraphDoc } from "./workflows";

export const CARD = { width: 260, height: 64 };
/** The farthest the canvas zooms out, by any way (wheel, pinch, its buttons, Fit): where a card is still 24 px tall on the
 * screen, a pointer target WCAG 2.5.8 needs no spacing for (0.4 × 64 = 25.6). Each "+" scales below that; a step's
 * panel offers them unscaled (the owner's ruling on M26). */
export const MIN_ZOOM = 0.4;

export function layout(doc: GraphDoc): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph<object, NodeLabel, object>();
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 76, marginx: 0, marginy: 0 });
  g.setDefaultEdgeLabel(() => ({}));
  g.setNode(START, { ...CARD });
  // Steps by identity (`idKey`): an edge may spell its ends otherwise than the steps do.
  for (const node of nodesOf(doc)) g.setNode(idKey(node.id), { ...CARD });
  for (const node of entries(doc)) g.setEdge(START, idKey(node.id));
  for (const edge of edgesOf(doc)) {
    const [from, to] = [idKey(edge.from.node), idKey(edge.to.node)];
    if (g.hasNode(from) && g.hasNode(to)) g.setEdge(from, to);
  }
  dagre.layout(g);
  // dagre sets each node's centre; every card is the same size, so offsets from the start card's are the cards' own.
  const centre = (id: string) => {
    const { x = 0, y = 0 } = g.node(id);
    return { x, y };
  };
  const start = centre(START);
  const out = new Map<string, { x: number; y: number }>();
  for (const node of nodesOf(doc)) {
    const at = centre(idKey(node.id));
    out.set(node.id, { x: Math.round(at.x - start.x), y: Math.round(at.y - start.y) });
  }
  return out;
}
