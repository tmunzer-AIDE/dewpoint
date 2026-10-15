// SPDX-License-Identifier: Apache-2.0
// Simulating the draft (4d-1c; the simulation design §6.6, §7): the API's simulation routes, as the generated schema
// types them (B1). One request per submit, frozen with its key and revision, sent again as it is when its answer is
// lost (§7.1); where a simulation is, from its state (§7.2); how often it's read again.
import { queryOptions } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";

// `version_id` is always null for a simulation, and openapi-fetch drops a key typed only as null from an answer.
export type SimulationRequest = Omit<Schemas["SimulationOut"], "version_id">;
export type SimulationState = Omit<Schemas["SimulationStateOut"], "request"> & { request: SimulationRequest };
export type SimulationRun = Schemas["SimulationRunOut"];
export type SimulationSteps = Schemas["SimulationStepsOut"];
export type StepSummary = Schemas["StepSummaryOut"];
export type StepInstances = Schemas["StepInstancesOut"];
export type SeedContract = Schemas["SeedContractOut"];
export type SeedEntry = Schemas["SeedEntryOut"];
export type DraftStartForm = Schemas["DraftStartFormOut"];
export type SimulateBody = Schemas["SimulateIn"];
export type DraftSnapshot = Schemas["DraftSnapshotOut"];
export type Origin = StepSummary["origin"];

/** A simulation as the editor sent it: its key, the revision it was frozen at and its body. An answer lost sends this
 * same request again; while the first is kept, the server answers it rather than start a second (§7.1). */
export interface Frozen {
  key: string;
  revision: number;
  body: SimulateBody;
}

export const freeze = (revision: number, body: SimulateBody, key: string = crypto.randomUUID()): Frozen => ({ key, revision, body });

const path = (tenantId: string, workflowId: string) => ({ tenant_id: tenantId, workflow_id: workflowId });

/** Sends a frozen simulation: its request, admitted (202), or an ApiError in the server's words. */
export function sendSimulation(tenantId: string, workflowId: string, frozen: Frozen): Promise<SimulationRequest> {
  return ok(
    client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", {
      params: {
        path: path(tenantId, workflowId),
        header: { "Idempotency-Key": frozen.key, "If-Match": String(frozen.revision) },
      },
      body: frozen.body,
    }),
  );
}

/** Cancels a simulation through its run's own route: `cancelled` when it was only queued, else `requested` (§6.6). */
export async function cancelSimulation(tenantId: string, requestId: string): Promise<"cancelled" | "requested"> {
  const answer = await ok(
    client.POST("/api/v1/t/{tenant_id}/runs/{request_id}/cancel", { params: { path: { tenant_id: tenantId, request_id: requestId } } }),
  );
  return (answer as { cancel?: unknown }).cancel === "cancelled" ? "cancelled" : "requested";
}

/** Where a simulation is (§7.2). `cancel_requested`: still going, never said cancelled before the server does. */
export type Phase =
  | "queued" | "starting" | "running" | "cancel_requested"
  | "succeeded" | "failed" | "cancelled" | "deadline_exceeded" | "refused" | "dead";  // prettier-ignore

export const ENDED: ReadonlySet<Phase> = new Set(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);

export function phaseOf(state: SimulationState): Phase {
  const { request, run, cancel_requested } = state;
  if (request.status === "queued" || request.status === "cancelled" || request.status === "refused" || request.status === "dead") {
    return request.status;
  }
  if (run === null || run.status === "running") return cancel_requested ? "cancel_requested" : run === null ? "starting" : "running";
  return run.status;
}

const STEPS = [1000, 1000, 2000, 3000];
/** How long until a simulation is read again, after `reads` reads: 1 s at first, backing off to 5 s (§7.2). */
export const pollEvery = (reads: number) => STEPS[reads] ?? 5000;

/** The draft's input as a form, at the revision a simulation will send (§7.1). */
export const draftStartFormQuery = (tenantId: string, workflowId: string, revision: number) =>
  queryOptions({
    queryKey: ["draft-start-form", tenantId, workflowId, revision],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/start-form", { params: { path: path(tenantId, workflowId), query: { revision } } })),
    staleTime: Infinity, // a revision's form never changes
  });

/** The person's latest simulation of the workflow, or null: what a reload finds (§7.1, "your latest simulation"). */
export const latestSimulationQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["simulations", tenantId, workflowId, "latest"],
    queryFn: async () =>
      (await ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", { params: { path: path(tenantId, workflowId), query: { limit: 1 } } })))[0] ?? null,
  });

/** A simulation where it is, its request and run, and what it ran with, redacted (§6.6). */
export const simulationStateQuery = (tenantId: string, workflowId: string, requestId: string) =>
  queryOptions({
    queryKey: ["simulation", tenantId, workflowId, requestId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}", { params: { path: { ...path(tenantId, workflowId), request_id: requestId } } })),
  });

/** A simulation's steps in run order, each with its counts and its data origin (§6.6, §7.4). */
export const simulationStepsQuery = (tenantId: string, workflowId: string, requestId: string) =>
  queryOptions({
    queryKey: ["simulation-steps", tenantId, workflowId, requestId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps", { params: { path: { ...path(tenantId, workflowId), request_id: requestId } } })),
  });

/** A page of a step's instances, one per iteration, in iteration order (§6.6). */
export const stepInstancesQuery = (
  tenantId: string, workflowId: string, requestId: string, stepId: string, page: { offset: number; limit: number; within?: string },
) =>
  queryOptions({
    queryKey: ["simulation-instances", tenantId, workflowId, requestId, stepId, page.offset, page.limit, page.within ?? null],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps/{step_id}/instances", {
        params: { path: { ...path(tenantId, workflowId), request_id: requestId, step_id: stepId }, query: { offset: page.offset, limit: page.limit, within: page.within } },
      })),
  });  // prettier-ignore

/** The draft a simulation ran, as frozen for it (§6.5): never changes, so it's read once. */
export const draftSnapshotQuery = (tenantId: string, workflowId: string, snapshotId: string) =>
  queryOptions({
    queryKey: ["draft-snapshot", tenantId, workflowId, snapshotId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/snapshots/{snapshot_id}", { params: { path: { ...path(tenantId, workflowId), snapshot_id: snapshotId } } })),
    staleTime: Infinity,
  });

/** A step's seed contract at a revision, each value prefilled where its step's own sample allows (§6.6, D-s2). */
export const seedContractQuery = (tenantId: string, workflowId: string, stepId: string, revision: number) =>
  queryOptions({
    queryKey: ["seed-contract", tenantId, workflowId, stepId, revision],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/steps/{step_id}/seeds", {
        params: { path: { ...path(tenantId, workflowId), step_id: stepId }, query: { revision } },
      })),
  });  // prettier-ignore
