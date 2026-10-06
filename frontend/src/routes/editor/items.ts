// SPDX-License-Identifier: Apache-2.0
// The canvas's items: what its one roving tab stop moves among (4b ruling 15), and what each action targets.
import { START, edgeId, idKey, type PortRef } from "../../lib/graph";
import type { GraphEdge } from "../../lib/workflows";

// A step's items are named by its id's identity (`idKey`), so two spellings of one step are one item.
export const item = {
  start: START,
  node: (id: string) => `node:${idKey(id)}`,
  edge: (edge: GraphEdge) => `edge:${edgeId(edge)}`,
  entry: (id: string) => `entry:${idKey(id)}`,
  port: (node: string, port: string) => `port:${idKey(node)}:${port}`,
};

export type ItemAction =
  | { kind: "open"; node: string }
  | { kind: "after"; from: PortRef | null }
  | { kind: "insert"; edge: GraphEdge }
  | { kind: "before"; entry: string };
