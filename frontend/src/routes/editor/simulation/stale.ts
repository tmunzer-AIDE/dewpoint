// SPDX-License-Identifier: Apache-2.0
// A simulation's result from before the person's edits (4d-1c; the simulation design §7.7; the Stale board): the
// server's draft has moved on from the revision it ran, or there are edits here not saved yet (the editor's generation,
// as publish's findings are dated). Which steps changed since, are new since or are gone comes from the draft it ran
// (its snapshot) against the draft as it is, by identity: a step moved, or an option left at its default, isn't a
// change. A step's own definition only: a rewired edge is covered by the banner, not marked on a step.
import { idKey, nodesOf } from "../../../lib/graph";
import type { GraphDoc, GraphNode } from "../../../lib/workflows";

export type Stale = { kind: "revision"; from: number; to: number } | { kind: "local" };
/** Steps by identity (`idKey`). */
export interface Changes {
  changed: Set<string>;
  added: Set<string>;
  gone: Set<string>;
}

/** The look of "Before your edits" (the Stale board: a warning, never the simulation's slate). */
export const STALE = "rounded-md border border-warn-line bg-warn-bg px-2.5 py-2 text-small text-warn-ink";

/** Whether a result for `revision` is before the person's edits. */
export function staleOf(revision: number, sync: { revision: number; generation: number; savedGeneration: number }): Stale | null {
  if (sync.revision !== revision) return { kind: "revision", from: revision, to: sync.revision };
  return sync.generation !== sync.savedGeneration ? { kind: "local" } : null;
}

/** What follows "Before your edits:"; the panel says what to do. */
export function staleWords(stale: Stale, panel: boolean): string {
  const said =
    stale.kind === "revision"
      ? `this result is for revision ${stale.from}; the draft is at revision ${stale.to}.`
      : "you've changed the draft since this result, and those changes aren't saved yet.";
  return panel ? `${said} Simulate again to see the draft as it is.` : said;
}

/** JSON with its keys sorted, undefined left out: two spellings of one value are one text. */
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v !== null && typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>).filter(([, x]) => x !== undefined);
    return `{${entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([k, x]) => `${JSON.stringify(k)}:${canonical(x)}`).join(",")}}`;
  }
  return JSON.stringify(v) ?? "null";
}

const DEFAULTS = { timeout_s: null, max_attempts: null, on_error: "fail" }; // engine/graph/model.py's Options
const definition = (n: GraphNode) => {
  const options = Object.fromEntries(Object.entries(n.options ?? {}).filter(([, x]) => x !== undefined));
  return canonical({ key: n.key, type: n.type, config: n.config ?? {}, options: { ...DEFAULTS, ...options } });
};

/** The steps changed since `ran`, new since, and gone, in the draft's order (gone ones in the snapshot's). */
export function changesOf(ran: GraphDoc, doc: GraphDoc): Changes {
  const before = new Map(nodesOf(ran).map((n) => [idKey(n.id), definition(n)]));
  const now = new Set(nodesOf(doc).map((n) => idKey(n.id)));
  const changes: Changes = { changed: new Set(), added: new Set(), gone: new Set() };
  for (const n of nodesOf(doc)) {
    const was = before.get(idKey(n.id));
    if (was === undefined) changes.added.add(idKey(n.id));
    else if (was !== definition(n)) changes.changed.add(idKey(n.id));
  }
  for (const id of before.keys()) if (!now.has(id)) changes.gone.add(id);
  return changes;
}
