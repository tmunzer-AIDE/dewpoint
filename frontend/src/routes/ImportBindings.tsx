// SPDX-License-Identifier: Apache-2.0
// Each id a workflow file names (a connection, a workflow) bound to one of this tenant's, or left unbound (B12; 4b
// ruling 18). A connection binding offers only connections of its type. Leaving one unbound is a choice the person
// makes, from what was read (ruling 28): each binding starts at "Choose…", the import waits for every one, and while
// this tenant's connections and workflows are loading, or when they couldn't be read, no choice is offered.
import { useQuery } from "@tanstack/react-query";
import { Button } from "../components/Button";
import { Select } from "../components/Field";
import { client, ok } from "../lib/client";
import { workflowsQuery, type WorkflowDocument } from "../lib/workflows";

/** Each binding's choice: one of this tenant's ids, or UNBOUND. A binding without one hasn't been chosen. */
export type Chosen = Record<string, string>;
export const UNBOUND = "unbound"; // never an id: ids are UUIDs

export type Choices = {
  state: "ready" | "loading" | "failed";
  connections: { id: string; name: string; type: string }[];
  workflows: { id: string; name: string }[];
  retry: () => void;
};

/** This tenant's connections and workflows, read only when a binding needs them; "ready" only once each needed list
 * was read, never an empty list standing in for one that wasn't. */
export function useBindingChoices(tenantId: string, bindings: WorkflowDocument["bindings"]): Choices {
  const needConnections = bindings.some((b) => b.kind === "connection");
  const needWorkflows = bindings.some((b) => b.kind === "workflow");
  const connections = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
    enabled: needConnections,
  });
  const workflows = useQuery({ ...workflowsQuery(tenantId), enabled: needWorkflows });
  const needed = [...(needConnections ? [connections] : []), ...(needWorkflows ? [workflows] : [])];
  const state = needed.some((q) => q.isError) ? "failed" : needed.every((q) => q.isSuccess) ? "ready" : "loading";
  return {
    state,
    connections: (connections.data ?? []).map((c) => ({ id: c.id, name: c.name, type: c.type })),
    workflows: (workflows.data ?? []).map((w) => ({ id: w.id, name: w.name })),
    retry: () => {
      if (connections.isError) void connections.refetch();
      if (workflows.isError) void workflows.refetch();
    },
  };
}

export function ImportBindings({
  bindings,
  choices,
  chosen,
  onChange,
}: {
  bindings: WorkflowDocument["bindings"];
  choices: Choices;
  chosen: Chosen;
  onChange: (chosen: Chosen) => void;
}) {
  if (bindings.length === 0) return <p className="text-small text-muted">The file names no connection or workflow.</p>;
  if (choices.state === "loading") {
    return <p className="text-small text-muted">Reading this tenant&apos;s connections and workflows…</p>;
  }
  if (choices.state === "failed") {
    return (
      <p role="alert" className="flex flex-wrap items-center gap-2 text-small text-danger">
        This tenant&apos;s connections or workflows couldn&apos;t be read, so nothing can be bound yet.
        <Button size="sm" onClick={choices.retry}>Try again</Button>
      </p>
    );
  }
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 text-small font-semibold">What the file names, bound to this tenant&apos;s</legend>
      {bindings.map((b) => {
        const options =
          b.kind === "connection"
            ? choices.connections.filter((c) => c.type === b.type)
            : choices.workflows;
        const places = `${b.sites.length} place${b.sites.length === 1 ? "" : "s"} in the graph`;
        const none = b.kind === "connection" ? `No ${b.type} connection in this tenant: choose Leave unbound.` : "No workflow in this tenant: choose Leave unbound.";
        return (
          <Select
            key={b.id}
            label={`${b.label} (${b.kind === "connection" ? `${b.type} connection` : "workflow"})`}
            hint={options.length === 0 ? none : places}
            value={chosen[b.id] ?? ""}
            onChange={(e) => onChange({ ...chosen, [b.id]: e.target.value })}
          >
            <option value="" disabled>Choose…</option>
            <option value={UNBOUND}>Leave unbound</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </Select>
        );
      })}
    </fieldset>
  );
}
