// SPDX-License-Identifier: Apache-2.0
// A tenant's connections, as the step drawer's pickers, a start form's picker fields and a picker field's editor read
// them (4c-1; the 4f-3 design §5.2, §5.7): one query, under Connections' own key, so each page sees the other's
// changes; a connection's status in words; and the types the plugins declare, each said by its label (4f-1).
import { queryOptions } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";

/** A connection's status in words, beside its name (ruling 107): "Acme Prod · verified". */
export const CONNECTION_STATUS: Record<Schemas["ConnectionOut"]["status"], string> = {
  ok: "verified",
  unverified: "not verified yet",
  error: "failed its last check",
};

/** The connection types the plugins declare, under Connections' own key: a type is said by its label (4f-1), read once
 * a session (ruling 335; F6): the plugins change only with a deploy. */
export const connectionTypesQuery = () =>
  queryOptions({ queryKey: ["connection-types"], queryFn: () => ok(client.GET("/api/v1/connection-types")), staleTime: Infinity });

/** The tenant's connections, under Connections' own key: each page sees the other's changes. */
export const connectionsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
  });
