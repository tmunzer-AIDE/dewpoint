// SPDX-License-Identifier: Apache-2.0
// The workflows list (screen 1a; 4b rulings 4-7): each workflow's state at a glance, filters, the enable switch for
// publishers, and export. No delete: no route deletes a workflow.
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "../components/Button";
import { MoreIcon } from "../components/icons";
import { LoadError } from "../components/LoadError";
import { Segmented } from "../components/Segmented";
import { Switch } from "../components/Switch";
import { Table, Td, Th } from "../components/Table";
import { announce } from "../lib/announce";
import { ApiError, client, ok } from "../lib/client";
import { downloadJson, fileName } from "../lib/download";
import { useDocumentTitle } from "../lib/title";
import { canEdit, canPublish, notPortable, since, tenantQuery, workflowsQuery, type PortableProblem, type WorkflowRow } from "../lib/workflows";
import { NewWorkflow } from "./NewWorkflow";

type Filter = "all" | "published" | "unpublished" | "attention";

// Never published counts as unpublished changes (4b ruling 6): the server says so in `unpublished_changes`.
const FILTERS: { value: Filter; label: string; keep: (w: WorkflowRow) => boolean }[] = [
  { value: "all", label: "All", keep: () => true },
  { value: "published", label: "Published", keep: (w) => w.active_version_id !== null },
  { value: "unpublished", label: "Unpublished changes", keep: (w) => w.unpublished_changes },
  { value: "attention", label: "Needs attention", keep: (w) => w.needs_attention.length > 0 },
];

const STATUS: Record<NonNullable<WorkflowRow["last_run"]>["status"], { text: string; dot: string }> = {
  running: { text: "Running", dot: "bg-accent" },
  succeeded: { text: "Succeeded", dot: "bg-ok" },
  failed: { text: "Failed", dot: "bg-danger" },
  cancelled: { text: "Cancelled", dot: "bg-line-strong" },
  deadline_exceeded: { text: "Ran out of time", dot: "bg-danger" },
};

function Version({ w }: { w: WorkflowRow }) {
  if (w.active_version_number === null) return <span className="text-muted">Not published</span>;
  return (
    <span className="font-mono text-small">
      v{w.active_version_number}
      {w.unpublished_changes && <span className="font-sans text-muted"> · unpublished changes</span>}
    </span>
  );
}

/** The last live run, what attention follows; the last simulation apart, in the simulation colour (4b ruling 7). */
function LastRun({ w }: { w: WorkflowRow }) {
  const live = w.last_run;
  const simulated = w.last_simulation;
  if (!live && !simulated) return <span className="text-muted">No runs yet</span>;
  return (
    <span className="flex flex-col gap-0.5 text-small">
      {live ? (
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className={`size-2 rounded-sm ${STATUS[live.status].dot}`} />
          {STATUS[live.status].text} · {since(live.at)}
        </span>
      ) : (
        <span className="text-muted">No live runs yet</span>
      )}
      {simulated && <span className="text-sim">Simulated: {STATUS[simulated.status].text} · {since(simulated.at)}</span>}
    </span>
  );
}

export function WorkflowsPage({ tenantId, startNew = false }: { tenantId: string; startNew?: boolean }) {
  useDocumentTitle("Workflows");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const list = useQuery(workflowsQuery(tenantId));
  const tenant = useQuery(tenantQuery(tenantId));
  const [filter, setFilter] = useState<Filter>("all");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(startNew);

  function closeNew() {
    setCreating(false);
    if (startNew) void navigate({ to: "/t/$tenantId/workflows", params: { tenantId }, search: {} });
  }

  const toggle = useMutation({
    mutationFn: (w: { id: string; name: string; enabled: boolean }) =>
      ok(
        client.PATCH("/api/v1/t/{tenant_id}/workflows/{workflow_id}", {
          params: { path: { tenant_id: tenantId, workflow_id: w.id } },
          body: { enabled: w.enabled },
        }),
      ),
    onMutate: () => setError(null),
    onSuccess: async (_, w) => {
      announce(`${w.name} switched ${w.enabled ? "on" : "off"}`);
      await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
    },
    onError: (e, w) => {
      const first = e instanceof ApiError && e.code === "not_enableable"
        ? (e.body as { diagnostics?: { message: string }[] }).diagnostics?.[0]?.message
        : undefined;  // prettier-ignore
      setError(first ? `${w.name} can't be switched on: ${first}` : `${w.name} couldn't be switched. Try again.`);
    },
  });

  async function exportOne(w: WorkflowRow) {
    try {
      const doc = await ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/export", {
          params: { path: { tenant_id: tenantId, workflow_id: w.id } },
        }),
      );
      downloadJson(fileName(w.name, ".dewpoint.json"), doc);
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_portable") {
        const problems = (e.body as { problems: PortableProblem[] }).problems;
        setError(`${w.name} can't be exported as a portable file: ${notPortable(problems)}. Open it to download the draft as it is.`);
        return;
      }
      setError(`${w.name} couldn't be exported. Try again.`);
    }
  }

  const rows = list.data ?? [];
  const named = rows.filter((w) => w.name.toLowerCase().includes(text.trim().toLowerCase()));
  const shown = named.filter(FILTERS.find((f) => f.value === filter)!.keep);
  const publisher = canPublish(tenant.data?.role);

  return (
    <section className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-h1 font-semibold">Workflows</h1>
        {canEdit(tenant.data?.role) && (
          <Button variant="primary" size="md" onClick={() => setCreating(true)} data-testid="workflow-new">
            New workflow
          </Button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex min-w-0 flex-1 basis-56 flex-col gap-1 sm:max-w-80">
          <span className="sr-only">Filter by name</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Filter by name"
            className="min-h-9 w-full rounded-lg border border-line-control bg-surface px-3 text-body placeholder:text-muted"
          />
        </label>
        <Segmented
          label="Show"
          value={filter}
          onChange={setFilter}
          options={FILTERS.map((f) => ({ value: f.value, label: f.label, count: named.filter(f.keep).length }))}
        />
      </div>
      {error && <p role="alert" className="text-body text-danger">{error}</p>}
      {list.isError ? (
        <LoadError what="The workflows" />
      ) : (
        <Table label="Workflows">
          <thead>
            <tr>
              <Th>Name</Th><Th>Version</Th><Th>Last run</Th><Th>Last 24 h</Th><Th>Enabled</Th>
              <Th><span className="sr-only">Actions</span></Th>
            </tr>
          </thead>
          <tbody>
            {shown.map((w) => (
              <tr key={w.id}>
                <Td>
                  <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: w.id }} className="font-medium text-accent-ink">
                    {w.name}
                  </Link>
                </Td>
                <Td><Version w={w} /></Td>
                <Td><LastRun w={w} /></Td>
                <Td className="font-mono text-small">
                  {w.runs_24h.live}
                  {w.runs_24h.simulate > 0 && <span className="font-sans text-sim"> +{w.runs_24h.simulate} simulated</span>}
                </Td>
                <Td>
                  {publisher ? (
                    <Switch
                      checked={w.enabled}
                      label={`Enable ${w.name}`}
                      disabled={toggle.isPending}
                      onCheckedChange={(enabled) => toggle.mutate({ id: w.id, name: w.name, enabled })}
                    />
                  ) : (
                    <span className="text-small">{w.enabled ? "On" : "Off"}</span>
                  )}
                </Td>
                <Td className="text-right">
                  <Dropdown.Root modal={false}>
                    <Dropdown.Trigger aria-label={`Actions for ${w.name}`} className="inline-grid min-h-8 place-items-center rounded-md border border-line-strong bg-surface px-2 text-small text-ink hover:bg-surface-hover">
                      <MoreIcon />
                    </Dropdown.Trigger>
                    <Dropdown.Portal>
                      <Dropdown.Content align="end" sideOffset={4} className="min-w-40 rounded-lg border border-line bg-surface p-1 shadow-dialog">
                        <Dropdown.Item
                          onSelect={() => void navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: w.id } })}
                          className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
                        >
                          Open
                        </Dropdown.Item>
                        <Dropdown.Item
                          onSelect={() => void exportOne(w)}
                          className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
                        >
                          Export
                        </Dropdown.Item>
                      </Dropdown.Content>
                    </Dropdown.Portal>
                  </Dropdown.Root>
                </Td>
              </tr>
            ))}
            {list.data && shown.length === 0 && (
              <tr>
                <Td colSpan={6} className="text-muted">{rows.length === 0 ? "No workflows yet." : "No workflow matches."}</Td>
              </tr>
            )}
          </tbody>
        </Table>
      )}
      <p className="text-small text-muted">A disabled workflow keeps its versions and its history; nothing starts it.</p>
      {/* Asked for by the address (?new) too: opened only once the role is known to create one. */}
      {creating && canEdit(tenant.data?.role) && <NewWorkflow tenantId={tenantId} onClose={closeNew} />}
    </section>
  );
}
