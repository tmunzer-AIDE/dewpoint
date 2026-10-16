// SPDX-License-Identifier: Apache-2.0
// A tenant's runs (editor 4e-1; the runs design §4, §5): the API's run routes as the generated schema types them (B1).
// The Runs page's filters, kept in its address; the list as read again and paged; a run, its steps, their instances
// and attempts, its input read back; its cancel.
import { queryOptions } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";

export type RunItem = Schemas["RunItemOut"];
export type Run = Schemas["RunOut"];
export type RunSteps = Schemas["RunStepsOut"];
export type RunStepSummary = Schemas["RunStepSummaryOut"];
export type RunStep = Schemas["RunStepOut"];
export type RunInput = Schemas["RunInputOut"];
export type Cancel = Schemas["CancelOut"];
export type RunOrigin = RunStepSummary["origin"];

/** The runs a page holds. */
export const PAGE = 50;

// The filters, one value each (§5.2). Each has a default the address leaves out: any workflow, status and trigger,
// live runs and simulations of a published version, the last 24 hours.
const STATUSES = ["waiting", "running", "succeeded", "failed", "deadline_exceeded", "cancelled", "didnt_start"] as const;
const TRIGGERS = ["manual", "rerun", "schedule", "webhook"] as const;
const MODES = ["both", "live", "simulated", "drafts", "everything"] as const;
const STARTED = ["1h", "24h", "7d", "30d", "all"] as const;
export type StatusFilter = (typeof STATUSES)[number];
export type TriggerFilter = (typeof TRIGGERS)[number];
export type ModeFilter = (typeof MODES)[number];
export type StartedFilter = (typeof STARTED)[number];
export interface RunFilters {
  workflow?: string;
  status?: StatusFilter;
  trigger?: TriggerFilter;
  mode?: ModeFilter;
  started?: StartedFilter;
}

const one = <T extends string>(allowed: readonly T[], v: unknown): T | undefined => (allowed.includes(v as T) ? (v as T) : undefined);

/** The filters an address holds, each value one it allows: a link keeps them (§5.1). Every filter is named, a value
 * it doesn't allow as undefined: the router lays a route's search over the address's own, which would keep it. */
export function validateRunsSearch(search: Record<string, unknown>): RunFilters {
  return {
    workflow: typeof search.workflow === "string" && search.workflow !== "" ? search.workflow : undefined,
    status: one(STATUSES, search.status),
    trigger: one(TRIGGERS, search.trigger),
    mode: one(MODES, search.mode),
    started: one(STARTED, search.started),
  };
}

/** The filters as an address writes them: those at their default left out. */
export function searchOf(f: RunFilters): RunFilters {
  const kept: RunFilters = { ...f, mode: f.mode === "both" ? undefined : f.mode, started: f.started === "24h" ? undefined : f.started };
  return Object.fromEntries(Object.entries(kept).filter(([, v]) => v !== undefined));
}

const SPAN: Record<StartedFilter, number | null> = { "1h": 3_600_000, "24h": 86_400_000, "7d": 7 * 86_400_000, "30d": 30 * 86_400_000, all: null };
const MODE: Record<ModeFilter, { mode?: "live" | "simulate"; draft: "exclude" | "only" | "include" }> = {
  both: { draft: "exclude" },
  live: { mode: "live", draft: "exclude" },
  simulated: { mode: "simulate", draft: "exclude" },
  drafts: { draft: "only" },
  everything: { draft: "include" },
};

/** What the filters ask of the API (§4.2); the window starts `now` less its span. */
export function paramsOf(f: RunFilters, now: number) {
  const span = SPAN[f.started ?? "24h"];
  const params = {
    workflow_id: f.workflow,
    status: f.status,
    source: f.trigger,
    ...MODE[f.mode ?? "both"],
    since: span === null ? undefined : new Date(now - span).toISOString(),
  };
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined)) as typeof params;
}

export interface Cursor {
  before: string;
  before_id: string;
}

/** A page of runs, newest first, after `cursor` when given. Its window is counted from when it's read. */
export const runsQuery = (tenantId: string, filters: RunFilters, cursor: Cursor | null = null) =>
  queryOptions({
    queryKey: ["runs", tenantId, searchOf(filters), cursor],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/runs", {
        params: { path: { tenant_id: tenantId }, query: { ...paramsOf(filters, Date.now()), ...cursor, limit: PAGE } },
      })),
  });  // prettier-ignore

// The list's order (§4.2): newest queued first, then by id; a run with no queue time (from before 2b-2) first.
const at = (i: RunItem) => (i.queued_at === null ? Infinity : Date.parse(i.queued_at));
const newer = (a: RunItem, b: RunItem) => at(b) - at(a) || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0);

/** The list shown (§5.2): the first page as last read, then the runs read earlier that sort after its last, each
 * once, the latest read of each. Those come from "Load more", or were pushed off the first page by newer runs: they're
 * no longer read again. A first page that isn't full holds every match, so nothing read earlier is kept; nor is a run
 * that sorts within the first page and isn't on it any more (it no longer matches). */
export function listed(first: RunItem[], earlier: RunItem[]): RunItem[] {
  const last = first.at(-1);
  if (first.length < PAGE || last === undefined) return first;
  const onFirst = new Set(first.map((i) => i.id));
  const kept = new Map<string, RunItem>();
  for (const i of earlier) if (!onFirst.has(i.id) && newer(last, i) < 0) kept.set(i.id, i);
  return [...first, ...[...kept.values()].sort(newer)];
}

/** Where the next page starts: after the last run listed. None after a run with no queue time: nothing sorts after it. */
export function cursorOf(items: RunItem[]): Cursor | null {
  const last = items.at(-1);
  return last?.queued_at ? { before: last.queued_at, before_id: last.id } : null;
}

const ENDED = new Set<RunItem["status"]>(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);
export const isEnded = (status: RunItem["status"]) => ENDED.has(status);

const path = (tenantId: string, runId: string) => ({ tenant_id: tenantId, run_id: runId });

/** A run, or a request that hasn't started, as itself (§4.3, §4.5). */
export const runQuery = (tenantId: string, runId: string) =>
  queryOptions({
    queryKey: ["run", tenantId, runId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}", { params: { path: path(tenantId, runId) } })),
  });

/** A run's steps in run order, summarized (§4.4). */
export const runStepsQuery = (tenantId: string, runId: string) =>
  queryOptions({
    queryKey: ["run-steps", tenantId, runId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/steps", { params: { path: path(tenantId, runId) } })),
  });

/** A page of a step's instances in a run, in iteration order, under an iteration when `within` names one (§4.4). */
export const runInstancesQuery = (tenantId: string, runId: string, stepId: string, page: { offset: number; limit: number; within?: string }) =>
  queryOptions({
    queryKey: ["run-instances", tenantId, runId, stepId, page.offset, page.limit, page.within ?? null],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/steps/{step_id}/instances", {
        params: { path: { ...path(tenantId, runId), step_id: stepId }, query: { offset: page.offset, limit: page.limit, within: page.within } },
      })),
  });  // prettier-ignore

/** One instance's attempts, first to last (§4.4): at most 20. */
export const runAttemptsQuery = (tenantId: string, runId: string, stepId: string, iteration: string) =>
  queryOptions({
    queryKey: ["run-attempts", tenantId, runId, stepId, iteration],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/steps/{step_id}/attempts", {
        params: { path: { ...path(tenantId, runId), step_id: stepId }, query: { iteration } },
      })),
  });  // prettier-ignore

/** What a run was admitted with, read back, redacted (§4.3). */
export const runInputQuery = (tenantId: string, runId: string) =>
  queryOptions({
    queryKey: ["run-input", tenantId, runId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/runs/{run_id}/input", { params: { path: path(tenantId, runId) } })),
  });

/** Cancels a run through its own route: `cancelled` when it was only queued, else `requested` (§5.3). */
export const cancelRun = (tenantId: string, requestId: string): Promise<Cancel> =>
  ok(client.POST("/api/v1/t/{tenant_id}/runs/{request_id}/cancel", { params: { path: { tenant_id: tenantId, request_id: requestId } } }));

// The roles that hold run.cancel (backend/src/dewpoint/core/authz/permissions.py: operator and above). The UI only
// hides what the API would refuse.
const CANCELLERS = new Set(["owner", "admin", "editor", "operator"]);
export const canCancel = (role?: string | null) => !!role && CANCELLERS.has(role);
