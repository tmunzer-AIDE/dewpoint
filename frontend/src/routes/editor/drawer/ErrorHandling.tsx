// SPDX-License-Identifier: Apache-2.0
// What a step's failure does, in words (4c-1, ruling 10; §10.3's chip), with the attempts and timeout the step sets
// when they differ from its type's.
import type { GraphNode, NodeType } from "../../../lib/workflows";

const CHIP = { fail: "fail the run", continue: "continue", port: "route to the error port" } as const;

export function chipText(node: GraphNode, type: NodeType | undefined): string {
  const own = node.options ?? {};
  const parts = [`On error: ${CHIP[own.on_error ?? "fail"]}`];
  if (own.max_attempts != null && own.max_attempts !== type?.retry.max_attempts) {
    parts.push(`${own.max_attempts} ${own.max_attempts === 1 ? "attempt" : "attempts"}`);
  }
  if (own.timeout_s != null && own.timeout_s !== type?.timeout_s) parts.push(`${own.timeout_s} s`);
  return parts.join(" · ");
}
