// SPDX-License-Identifier: Apache-2.0
// Choosing what a step uses from the tenant's own (4c-1, rulings 12 and 13): a connection of the field's type, its
// status in words, or another workflow. A value naming nothing here is said to, until it's changed.
import { queryOptions, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { client, ok, type Schemas } from "../../../lib/client";
import { sameId } from "../../../lib/graph";
import { workflowsQuery } from "../../../lib/workflows";
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

type Connection = Schemas["ConnectionOut"];
const STATUS: Record<Connection["status"], string> = {
  ok: "verified",
  unverified: "not verified yet",
  error: "failed its last check",
};

/** The tenant's connections, under Connections' own key: each page sees the other's changes. */
export const connectionsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
  });

function Failed({ what, retry }: { what: string; retry: () => void }) {
  return (
    <p className="flex flex-wrap items-center gap-2 text-small text-danger">
      {what} couldn&apos;t load.
      <Button size="sm" onClick={retry}>Try again</Button>
    </p>
  );
}

export function ConnectionControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const { tenantId } = useDrawer();
  const marker = spec.schema["x-dewpoint-connection"];
  const kind = typeof marker === "string" ? marker : "";
  const list = useQuery(connectionsQuery(tenantId));
  if (list.isPending) return <p className="text-small text-muted">Loading connections…</p>;
  if (list.isError) return <Failed what="Connections" retry={() => void list.refetch()} />;
  const mine = list.data.filter((c) => c.type === kind);
  const current = typeof value === "string" ? value : "";
  const known = current !== "" && mine.some((c) => sameId(c.id, current));
  if (mine.length === 0 && current === "") {
    return kind === "mist" ? (
      <p className="text-small">
        No Mist connection yet.{" "}
        <Link to="/t/$tenantId/connections" params={{ tenantId }} className="font-semibold underline">
          Add one in Connections
        </Link>
        .
      </p>
    ) : (
      <p className="text-small">No {kind} connection yet: an admin adds one.</p>
    );
  }
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, false)}
      className={controlClass(invalid)}
    >
      <option value="">Choose a connection</option>
      {current !== "" && !known && <option value={current}>A connection that isn&apos;t in this tenant</option>}
      {mine.map((c) => (
        // The id as the step writes it, whatever its spelling, so the step's own stays chosen.
        <option key={c.id} value={known && sameId(c.id, current) ? current : c.id}>
          {c.name} · {STATUS[c.status]}
        </option>
      ))}
    </select>
  );  // prettier-ignore
}

export function WorkflowControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const { tenantId, workflowId } = useDrawer();
  const list = useQuery(workflowsQuery(tenantId));
  if (list.isPending) return <p className="text-small text-muted">Loading workflows…</p>;
  if (list.isError) return <Failed what="Workflows" retry={() => void list.refetch()} />;
  const others = list.data.filter((w) => !sameId(w.id, workflowId));
  const current = typeof value === "string" ? value : "";
  const known = current !== "" && others.some((w) => sameId(w.id, current));
  if (others.length === 0 && current === "") return <p className="text-small">No other workflow yet.</p>;
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, false)}
      className={controlClass(invalid)}
    >
      <option value="">Choose a workflow</option>
      {current !== "" && !known && <option value={current}>A workflow that isn&apos;t in this tenant</option>}
      {others.map((w) => (
        <option key={w.id} value={known && sameId(w.id, current) ? current : w.id}>{w.name}</option>
      ))}
    </select>
  );  // prettier-ignore
}
