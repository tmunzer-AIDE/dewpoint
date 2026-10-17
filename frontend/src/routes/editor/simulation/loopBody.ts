// SPDX-License-Identifier: Apache-2.0
// A loop's iterations in the Simulation panel (4d-1c; the simulation design §7.5; the ResultPanel board): which steps
// an iteration runs, how the engine keys an iteration, and what a step did in one, in words. Every opened iteration
// holds exactly one instance of each step directly in its body, skipped ones included (B4b), so a page of each step's
// instances is a page of iterations.
import { edgesOf, idKey, nodesOf, portOf, sameId } from "../../../lib/graph";
import type { GraphDoc, GraphNode } from "../../../lib/workflows";

const LOOP = "flow.loop@";
export const PAGE = 4;

/** Where a loop's instances are read (4e-1): under the simulation or the run they're of (`key`), a page of one step's
 * at a time, under an iteration when `within` names one. */
export interface InstancePages {
  key: readonly unknown[];
  read: (stepId: string, page: { offset: number; limit: number; within?: string }) => Promise<{ total: number; items: unknown[] }>;
}

/** Every step reachable from a loop's `body` port, as the engine reads a loop's region (engine/graph/structure.py). */
export function regionOf(doc: GraphDoc, loopId: string): Set<string> {
  const edges = edgesOf(doc);
  const region = new Set<string>();
  const queue = edges.filter((e) => sameId(e.from.node, loopId) && portOf(e) === "body").map((e) => idKey(e.to.node));
  for (let next = queue.shift(); next !== undefined; next = queue.shift()) {
    if (region.has(next)) continue;
    region.add(next);
    queue.push(...edges.filter((e) => idKey(e.from.node) === next).map((e) => idKey(e.to.node)));
  }
  return region;
}

/** The steps a loop's iteration runs itself, in the draft's order: not those of a loop nested in it, which run in
 * that loop's own iterations. */
export function bodyOf(doc: GraphDoc, loopId: string): GraphNode[] {
  const region = regionOf(doc, loopId);
  const nested = new Set<string>();
  for (const n of nodesOf(doc)) {
    if (n.type.startsWith(LOOP) && region.has(idKey(n.id))) for (const id of regionOf(doc, n.id)) nested.add(id);
  }
  return nodesOf(doc).filter((n) => region.has(idKey(n.id)) && !nested.has(idKey(n.id)));
}

/** An iteration's key as the engine writes it: `loop:index`, under the iterations it's nested in. */
export const iterationOf = (prefix: string, loopKey: string, index: number): string => `${prefix ? `${prefix}/` : ""}${loopKey}:${index}`;

const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);

/** What a step did in one iteration: the port it took, else a nested loop's count, else its status; a failure's code. */
export function cellOf(item: unknown, type: string): { text: string; failed: boolean; code: string | null } {
  if (item === undefined) return { text: "not recorded", failed: false, code: null };
  const status = typeof field(item, "status") === "string" ? (field(item, "status") as string) : "not recorded";
  const port = field(field(item, "effect"), "port");
  const count = field(field(item, "output"), "count");
  const code = field(field(item, "error"), "code");
  const text =
    status === "succeeded" && typeof port === "string" ? `→ ${port}`
    : status === "succeeded" && type.startsWith(LOOP) && typeof count === "number" ? `${count} ${count === 1 ? "iteration" : "iterations"}`
    : status.replace("_", " ");  // prettier-ignore
  return { text, failed: status === "failed", code: typeof code === "string" ? code : null };
}
