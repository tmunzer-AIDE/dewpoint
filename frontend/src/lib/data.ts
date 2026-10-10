// SPDX-License-Identifier: Apache-2.0
// The data a step's field can read, and a step's newest sample (4c-2b): the scope (B6, ledger rulings 117–120) and the
// samples (B7, rulings 122–123) of the saved draft, asked per revision, and how the drawer says them. The server
// decides every type, guard and sensitivity (D18): this only names them.
import { queryOptions } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";
import { headOf } from "./pills";

export type ScopeAnswer = Schemas["ScopeOut"];
export type ScopeEntry = Schemas["ScopeEntryOut"];
export type Guard = Schemas["GuardOut"];
export type SamplesAnswer = Schemas["SamplesOut"];
export type Sample = Schemas["SampleOut"];
export type SampleConnection = Schemas["SampleConnectionOut"];

/** What a field asks of its scope: the top of each root, one path's children, one path, or names containing text. */
export type Ask = { kind: "top" } | { kind: "under"; path: string } | { kind: "at"; path: string } | { kind: "find"; text: string };

/** Which field of which saved draft: an answer is for one revision, and a newer one asks again (D17). */
export interface Where {
  tenantId: string;
  workflowId: string;
  revision: number;
  node: string;
  field: string;
}

/** An answer about another revision than the one asked of: the API answers for the saved draft as it is, and it was
 * saved again meanwhile (D17). It's never shown as the asked revision's (the review of revision 1). */
export class DraftMoved extends Error {
  constructor(readonly revision: number) {
    super("The draft was saved again while its data was asked for. Close this and open it again.");
    this.name = "DraftMoved";
  }
}

const ofRevision =
  (revision: number) =>
  <T extends { draft_revision: number }>(answer: T): T => {
    if (answer.draft_revision !== revision) throw new DraftMoved(answer.draft_revision);
    return answer;
  };

const askQuery = (ask: Ask) =>
  ask.kind === "under" ? { under: ask.path } : ask.kind === "at" ? { at: ask.path } : ask.kind === "find" ? { find: ask.text } : {};

export const scopeQuery = (where: Where, ask: Ask) =>
  queryOptions({
    queryKey: ["scope", where.tenantId, where.workflowId, where.revision, where.node, where.field, ask],
    queryFn: () =>
      ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/scope", {
          params: {
            path: { tenant_id: where.tenantId, workflow_id: where.workflowId },
            query: { node: where.node, field: where.field, ...askQuery(ask) },
          },
        }),
      ).then(ofRevision(where.revision)),
    staleTime: Infinity, // a revision's answer doesn't change: the next revision asks again
  });

/** A step's newest sample, against the saved draft (B7). Asked for again each time it's shown: runs end, connections
 * change and history expires whatever the draft's revision (the review of revision 1). */
export const samplesQuery = (where: Omit<Where, "field">, iteration?: string) =>
  queryOptions({
    queryKey: ["samples", where.tenantId, where.workflowId, where.revision, where.node, iteration ?? null],
    queryFn: () =>
      ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/samples", {
          params: {
            path: { tenant_id: where.tenantId, workflow_id: where.workflowId },
            query: { node: where.node, ...(iteration === undefined ? {} : { iteration }) },
          },
        }),
      ).then(ofRevision(where.revision)),
    staleTime: 0,
  });

const WORDS: Record<string, string> = {
  string: "text",
  integer: "whole number",
  number: "number",
  boolean: "yes or no",
  array: "list",
  object: "object",
};

/** A value's type in words: what the tree and a pill's details say. */
export function typeWords(entry: Pick<ScopeEntry, "types" | "format">): string {
  const types = entry.types.filter((t) => t !== "null");
  if (entry.types.length === 0) return "any value";
  if (types.length === 0) return "always null";
  return types
    .map((t) => (t === "string" && entry.format === "date-time" ? "date and time" : (WORDS[t] ?? t)))
    .join(" or ");
}

export interface Tag {
  text: string;
  conditional: boolean; // drawn dashed, as a conditional pill is
}

/** What a value may do when the step runs, and whether a reference to it holds sensitive data. */
export function tagsOf(entry: Pick<ScopeEntry, "missing" | "nullable" | "sensitive">): Tag[] {
  return [
    entry.missing ? { text: "may be missing", conditional: true } : null,
    entry.nullable ? { text: "may be null", conditional: false } : null,
    entry.sensitive ? { text: "sensitive", conditional: false } : null,
  ].filter((t): t is Tag => t !== null);
}

/** The group a root's entries show under: a step by its key and its type's title, the others by what they are. */
export function groupOf(entry: Pick<ScopeEntry, "root" | "path">, titleOf: (key: string) => string | null): { key: string; title: string; detail: string | null } {
  const { head } = headOf(entry.path);
  switch (entry.root) {
    case "steps":
      return { key: `steps.${head}`, title: head, detail: titleOf(head) };
    case "loops":
      return { key: `loops.${head}`, title: head, detail: "its loop's item" };
    case "trigger":
      return { key: "trigger", title: "Trigger", detail: null };
    case "vars":
      return { key: "vars", title: "Variables", detail: null };
    case "run":
      return { key: "run", title: "This run", detail: null };
    default:
      return { key: entry.root, title: "This item", detail: null }; // item and index
  }
}

/** Why a value may be missing or null, from the guards a formula needs to read it (ruling 119): the server's own
 * reasons, in words. Empty when it's always there. */
export function whyMissing(entry: Pick<ScopeEntry, "formula" | "missing" | "nullable" | "path" | "types" | "root">): string[] {
  const guards = entry.formula?.guards ?? [];
  const reasons: string[] = [];
  for (const g of guards) {
    const step = /^steps\.([A-Za-z_][A-Za-z0-9_]*)\.(output|error)$/.exec(g.path);
    if (g.kind === "present" && step) reasons.push(`${step[1]} may not run`);
    else if (g.kind === "present") reasons.push(g.path === entry.path ? "it's optional in its data" : `${g.path} is optional`);
    else if (g.kind === "not_null" && g.path !== entry.path) reasons.push(`${g.path} may be null`);
    else if (g.kind === "min_size") reasons.push(`${g.path} may have fewer items`);
    else if (g.kind === "is_map" || g.kind === "is_list") reasons.push(`${g.path} may be another kind of value`);
  }
  if (entry.root === "trigger" && entry.types.length === 0) reasons.push("the trigger's input isn't declared");
  if (entry.nullable) reasons.push("it may be null");
  return [...new Set(reasons)];
}

/** A value the run kept apart from its history (engine/handles.py: `{"$claim": id}`, a pointer maybe): not in a
 * preview (R6 §8). */
const claimed = (v: unknown): boolean =>
  typeof v === "object" && v !== null && !Array.isArray(v) && "$claim" in v && Object.keys(v).every((k) => k === "$claim" || k === "pointer");

/** What a preview kept at a path below a step's output: the value; a marker where the preview stopped (a `[redacted]`
 * or `[truncated]` that stands for the whole value, D20, or a value kept apart); or nothing, when that run's output
 * didn't hold it. */
export function previewAt(output: unknown, path: (string | number)[]): { value: unknown } | { marker: "redacted" | "truncated" | "claimed" | "absent" } {
  let at = output;
  for (const key of path) {
    if (at === "[redacted]") return { marker: "redacted" };
    if (at === "[truncated]") return { marker: "truncated" };
    if (claimed(at)) return { marker: "claimed" };
    if (typeof key === "number" && Array.isArray(at) && key < at.length) at = (at as unknown[])[key];
    else if (typeof key === "string" && typeof at === "object" && at !== null && !Array.isArray(at) && Object.hasOwn(at, key)) at = (at as Record<string, unknown>)[key];
    else return { marker: "absent" };
  }
  if (at === "[redacted]") return { marker: "redacted" };
  if (at === "[truncated]") return { marker: "truncated" };
  if (claimed(at)) return { marker: "claimed" };
  return { value: at };
}
