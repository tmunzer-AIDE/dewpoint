// SPDX-License-Identifier: Apache-2.0
// The canvas's items: what its one roving tab stop moves among (4b ruling 15), and what each action targets.
import { START, edgeId, type PortRef } from "../../lib/graph";
import type { GraphEdge } from "../../lib/workflows";

export const item = {
  start: START,
  node: (id: string) => `node:${id}`,
  edge: (edge: GraphEdge) => `edge:${edgeId(edge)}`,
  entry: (id: string) => `entry:${id}`,
  port: (node: string, port: string) => `port:${node}:${port}`,
};

export type ItemAction =
  | { kind: "open"; node: string }
  | { kind: "after"; from: PortRef | null }
  | { kind: "insert"; edge: GraphEdge }
  | { kind: "before"; entry: string };
