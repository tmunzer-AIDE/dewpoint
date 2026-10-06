// SPDX-License-Identifier: Apache-2.0
// The workflows list (screen 1a). Task 7 adds the filters, the enable switch and the row menu.
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { LoadError } from "../components/LoadError";
import { Table, Td, Th } from "../components/Table";
import { useDocumentTitle } from "../lib/title";
import { workflowsQuery } from "../lib/workflows";

export function WorkflowsPage({ tenantId }: { tenantId: string; startNew?: boolean }) {
  useDocumentTitle("Workflows");
  const list = useQuery(workflowsQuery(tenantId));
  return (
    <section className="flex flex-col gap-4 p-6">
      <h1 className="text-h1 font-semibold">Workflows</h1>
      {list.isError ? (
        <LoadError what="The workflows" />
      ) : (
        <Table label="Workflows">
          <thead>
            <tr><Th>Name</Th></tr>
          </thead>
          <tbody>
            {list.data?.map((w) => (
              <tr key={w.id}>
                <Td>
                  <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: w.id }} className="font-medium text-accent-ink">
                    {w.name}
                  </Link>
                </Td>
              </tr>
            ))}
            {list.data?.length === 0 && (
              <tr><Td className="text-muted">No workflows yet.</Td></tr>
            )}
          </tbody>
        </Table>
      )}
    </section>
  );
}
