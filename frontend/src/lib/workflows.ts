// SPDX-License-Identifier: Apache-2.0
// The workflow API's shapes and queries (sub-project 4, slice 4b): types from the generated schema (B1), never
// written by hand.
import { queryOptions } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";

export type WorkflowRow = Schemas["WorkflowOut"];
export type WorkflowDetail = Schemas["WorkflowDetailOut"];
export type GraphDoc = Schemas["Graph"];
export type GraphNode = Schemas["GraphNode"];
export type GraphEdge = Schemas["Edge"];
export type NodeType = Schemas["NodeTypeOut"];
export type Diagnostic = Schemas["DiagnosticOut"];
export type Validation = Schemas["ValidationOut"];
export type Expression = Schemas["ExpressionOut"];
export type VersionRow = Schemas["VersionOut"];
export type VersionDetail = Schemas["VersionDetailOut"];
export type WorkflowDocument = Schemas["WorkflowDocument"];

const tenantPath = (tenantId: string) => ({ params: { path: { tenant_id: tenantId } } });
const workflowPath = (tenantId: string, workflowId: string) => ({
  params: { path: { tenant_id: tenantId, workflow_id: workflowId } },
});

export const workflowsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["workflows", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows", tenantPath(tenantId))),
  });

export const workflowQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["workflow", tenantId, workflowId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}", workflowPath(tenantId, workflowId))),
    // No staleTime: the editor reads it afresh on every entry and seeds itself once (Task 13, 4b ruling 23).
  });

export const versionsQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["versions", tenantId, workflowId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions", workflowPath(tenantId, workflowId))),
  });

export const nodeTypesQuery = queryOptions({
  queryKey: ["node-types"],
  queryFn: () => ok(client.GET("/api/v1/node-types")),
  staleTime: 5 * 60_000,
});

export const tenantQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["tenant", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}", tenantPath(tenantId))),
  });

// The roles that hold workflow.edit and workflow.publish (backend/src/dewpoint/core/authz/permissions.py: editor and
// above). The UI only hides what the API would refuse: the API decides every write.
const EDITORS = new Set(["owner", "admin", "editor"]);
export const canEdit = (role?: string | null) => !!role && EDITORS.has(role);
export const canPublish = (role?: string | null) => !!role && EDITORS.has(role);

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** How long ago `iso` was, in words, then as a date. */
export function since(iso: string, now: number = Date.now()): string {
  const minutes = Math.floor((now - Date.parse(iso)) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  if (minutes < 48 * 60) return "yesterday";
  return DATE.format(new Date(iso));
}

/** One reason an export refused (B12; 4b ruling 18), as the API answers it. */
export type PortableProblem = { reason: string; binding: string | null; node: string | null; field: string | null };

/** Why a workflow can't be exported as a portable file, as a clause ("it has …"): its steps named when `keyOf`
 * knows them (the editor), not on the list, which holds no graph. */
export function notPortable(problems: PortableProblem[], keyOf?: (nodeId: string) => string): string {
  const names = (reason: string) =>
    problems.filter((p) => p.reason === reason).map((p) => (p.node === null ? "the failure handler" : keyOf ? keyOf(p.node) : p.node));
  const clause = (text: string, reason: string) => {
    const found = names(reason);
    return found.length === 0 ? null : keyOf ? `${text} (${found.join(", ")})` : text;
  };
  const why = [
    clause("steps of a type this server doesn't know", "unknown_type"),
    clause("something other than an id where a connection or workflow goes", "unexpected_value"),
    clause("two steps sharing an id", "duplicate_node"),
  ].filter((c): c is string => c !== null);
  return `it has ${why.join(", and ")}`;
}
