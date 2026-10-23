// SPDX-License-Identifier: Apache-2.0
// Choosing what a step uses from the tenant's own (4c-1, rulings 12 and 13): a connection of the field's type, its
// status in words, or another workflow. A value naming nothing here is said to, until it's changed.
import { queryOptions, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { client, ok } from "../../../lib/client";
import { CONNECTION_STATUS, connectionsQuery } from "../../../lib/connections";
import { sameId } from "../../../lib/graph";
import { workflowsQuery } from "../../../lib/workflows";
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

/** The connection types the plugins declare, under Connections' own key: a type is said by its label (4f-1). */
export const connectionTypesQuery = () =>
  queryOptions({ queryKey: ["connection-types"], queryFn: () => ok(client.GET("/api/v1/connection-types")) });

/** What a picker says in place of its list (loading, failed, nothing to choose): an `<output>` with the field's control
 * id, so the field's label names it (#73), as the drawer shows a value it doesn't edit. A list on its way is marked, so
 * a Go to waits for it. */
function Said({ id, describedBy, loading = false, className = "block text-small", children }: {
  id: string; describedBy: string | undefined; loading?: boolean; className?: string; children: ReactNode;
}) {  // prettier-ignore
  return (
    <output id={id} aria-describedby={describedBy} data-loading={loading || undefined} className={className}>
      {children}
    </output>
  );
}

function Failed({ id, describedBy, what, retry }: { id: string; describedBy: string | undefined; what: string; retry: () => void }) {
  return (
    <Said id={id} describedBy={describedBy} className="flex flex-wrap items-center gap-2 text-small text-danger">
      {what} couldn&apos;t load.
      <Button size="sm" onClick={retry}>Try again</Button>
    </Said>
  );
}

export function ConnectionControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const { tenantId } = useDrawer();
  const marker = spec.schema["x-dewpoint-connection"];
  const kind = typeof marker === "string" ? marker : "";
  const list = useQuery(connectionsQuery(tenantId));
  const said = { id, describedBy };
  const current = typeof value === "string" ? value : "";
  // Read only when there's none to choose: the words then name the type.
  const none = list.isSuccess && current === "" && kind !== "" && kind !== "mist" && !list.data.some((c) => c.type === kind);
  const types = useQuery({ ...connectionTypesQuery(), enabled: none });
  // Without its kind, no connection is the field's: none is listed, so none can be chosen. A value it has stays shown,
  // and can be cleared (the review).
  if (kind === "" && current === "") return <Said {...said}>This field doesn&apos;t say which kind of connection it takes.</Said>;
  if (list.isPending) return <Said {...said} loading className="block text-small text-muted">Loading connections…</Said>;
  if (list.isError) return <Failed {...said} what="Connections" retry={() => void list.refetch()} />;
  const mine = list.data.filter((c) => c.type === kind);
  const known = current !== "" && mine.some((c) => sameId(c.id, current));
  if (mine.length === 0 && current === "") {
    // Named by its label ("Slack", "Microsoft Teams"), never its key (4f-1, the message composer design §5.6).
    const label = types.data?.find((t) => t.key === kind)?.label;
    if (kind !== "mist" && types.isPending) return <Said {...said} loading className="block text-small text-muted">Loading connections…</Said>;
    return kind === "mist" ? (
      <Said {...said}>
        No Mist connection yet.{" "}
        <Link to="/t/$tenantId/connections" params={{ tenantId }} className="font-semibold underline">
          Add one in Connections
        </Link>
        .
      </Said>
    ) : (
      <Said {...said}>{label ? `No ${label} connection yet: an admin adds one.` : "No connection of its type yet: an admin adds one."}</Said>
    );
  }
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, false)}
      className={controlClass(invalid)}
    >
      <option value="">Choose a connection</option>
      {current !== "" && !known && <option value={current}>A connection that isn&apos;t in this tenant</option>}
      {mine.map((c) => (
        // The id as the step writes it, whatever its spelling, so the step's own stays chosen.
        <option key={c.id} value={known && sameId(c.id, current) ? current : c.id}>
          {c.name} · {CONNECTION_STATUS[c.status]}
        </option>
      ))}
    </select>
  );  // prettier-ignore
}

export function WorkflowControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const { tenantId, workflowId } = useDrawer();
  const list = useQuery(workflowsQuery(tenantId));
  const said = { id, describedBy };
  if (list.isPending) return <Said {...said} loading className="block text-small text-muted">Loading workflows…</Said>;
  if (list.isError) return <Failed {...said} what="Workflows" retry={() => void list.refetch()} />;
  const others = list.data.filter((w) => !sameId(w.id, workflowId));
  const current = typeof value === "string" ? value : "";
  const known = current !== "" && others.some((w) => sameId(w.id, current));
  if (others.length === 0 && current === "") return <Said {...said}>No other workflow yet.</Said>;
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
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
