// SPDX-License-Identifier: Apache-2.0
// The editor (screen 1c). Task 11 adds the canvas; Tasks 13-15 saving, problems and publishing.
import { useQuery } from "@tanstack/react-query";
import { LoadError } from "../../components/LoadError";
import { useDocumentTitle } from "../../lib/title";
import { nodeTypesQuery, workflowQuery } from "../../lib/workflows";

export function EditorPage({ tenantId, workflowId }: { tenantId: string; workflowId: string }) {
  const workflow = useQuery(workflowQuery(tenantId, workflowId));
  const types = useQuery(nodeTypesQuery);
  useDocumentTitle(workflow.data?.name ?? "Workflow");
  if (workflow.isError) return <section className="p-6"><LoadError what="This workflow" /></section>;
  if (types.isError) return <section className="p-6"><LoadError what="The step types" /></section>;
  if (!workflow.data || !types.data) return <p className="p-6 text-body text-muted">Loading…</p>;
  return (
    <section className="flex flex-col gap-4 p-6">
      <h1 className="text-h1 font-semibold">{workflow.data.name}</h1>
    </section>
  );
}
