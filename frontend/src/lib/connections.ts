// SPDX-License-Identifier: Apache-2.0
// A tenant's connections, as the step drawer's pickers and a start form's picker fields read them (4c-1; the 4f-3
// design §5.2): one query, under Connections' own key, so each page sees the other's changes.
import { queryOptions } from "@tanstack/react-query";
import { client, ok } from "./client";

/** The tenant's connections, under Connections' own key: each page sees the other's changes. */
export const connectionsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
  });
