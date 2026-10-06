// SPDX-License-Identifier: Apache-2.0
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../components/Button";
import { Field, Select } from "../components/Field";
import { StatusBadge } from "../components/StatusBadge";
import { Table, Td, Th } from "../components/Table";
import { ApiError, client, ok } from "../lib/client";

/** A Mist connection's config, as the Mist connection type declares it. */
interface MistConfig {
  cloud: string;
  org_id: string;
}

export function ConnectionsPage({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const path = { tenant_id: tenantId };
  const list = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path } })),
  });
  const types = useQuery({ queryKey: ["connection-types"], queryFn: () => ok(client.GET("/api/v1/connection-types")) });
  const clouds = types.data?.find((t) => t.key === "mist")?.clouds ?? {};
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", cloud: "global_01", org_id: "", api_token: "" });
  const [error, setError] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["connections", tenantId] });

  const create = useMutation({
    mutationFn: () =>
      ok(client.POST("/api/v1/t/{tenant_id}/connections", {
        params: { path },
        body: {
          type: "mist", name: form.name, config: { cloud: form.cloud, org_id: form.org_id },
          secret: { api_token: form.api_token },
        },
      })),
    onSuccess: async () => {
      setOpen(false);
      setForm({ name: "", cloud: "global_01", org_id: "", api_token: "" });
      await refresh();
    },
    onError: (e) => setError(e instanceof ApiError && e.code === "name_taken" ? "A connection with this name exists."
      : e instanceof ApiError && e.status === 403 ? "You don't have permission to manage connections."
      : "Check the fields and try again."),
  });
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const verify = useMutation({
    mutationFn: (id: string) =>
      ok(client.POST("/api/v1/t/{tenant_id}/connections/{connection_id}/verify", {
        params: { path: { ...path, connection_id: id } },
      })),
    onMutate: () => setVerifyError(null),
    onSuccess: refresh,
    onError: async (e) => {
      setVerifyError(
        e instanceof ApiError && e.code === "changed_during_verification"
          ? "The connection was edited while it was being verified. The result was discarded; verify again."
          : "Verification could not be completed.",
      );
      await refresh();
    },
  });

  return (
    <section className="flex flex-col gap-4 p-6">
      <h1 className="text-h1 font-semibold">Connections</h1>
      {verifyError && <p role="alert" className="text-body text-danger">{verifyError}</p>}
      <div className={`grid gap-5 ${open ? "grid-cols-[minmax(0,1fr)_400px]" : "grid-cols-1"}`}>
        <div className="flex min-w-0 flex-col gap-2.5">
          <div className="flex items-end justify-between gap-4">
            <div>
              <h2 className="text-body-lg font-semibold">Mist connections</h2>
              <p className="mt-0.5 text-small text-muted">Org-scoped API tokens. Privilege is read from Mist at verification.</p>
            </div>
            <Button variant="primary" size="md" onClick={() => setOpen(true)} data-testid="conn-add">
              Add Mist connection
            </Button>
          </div>
          <Table>
            <thead>
              <tr><Th>Name</Th><Th>Cloud</Th><Th>Org ID</Th><Th>Status</Th><Th><span className="sr-only">Actions</span></Th></tr>
            </thead>
            <tbody>
              {list.data?.map((c) => (
                <tr key={c.id} data-testid="conn-row">
                  <Td className="font-medium">{c.name}</Td>
                  <Td className="font-mono text-small">{clouds[(c.config as unknown as MistConfig).cloud] ?? (c.config as unknown as MistConfig).cloud}</Td>
                  <Td className="font-mono text-small">{(c.config as unknown as MistConfig).org_id}</Td>
                  <Td><StatusBadge status={c.status} detail={c.status_detail} privilege={c.privilege} /></Td>
                  <Td className="text-right">
                    <Button size="sm" onClick={() => verify.mutate(c.id)} disabled={verify.isPending}>Verify</Button>
                  </Td>
                </tr>
              ))}
              {list.data?.length === 0 && (
                <tr><Td colSpan={5} className="text-muted">No Mist connection yet.</Td></tr>
              )}
            </tbody>
          </Table>
        </div>
        {open && (
          <form aria-label="Add Mist connection" className="flex flex-col gap-3.5 self-start rounded-lg border border-line bg-surface p-5"
            onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
            <h2 className="text-body-lg font-semibold">Add Mist connection</h2>
            <Field label="Name" required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              data-testid="conn-name" />
            <Select label="Mist cloud" value={form.cloud} onChange={(e) => setForm({ ...form, cloud: e.target.value })}
              data-testid="conn-cloud">
              {Object.entries(clouds).map(([k, host]) => <option key={k} value={k}>{host}</option>)}
            </Select>
            <Field label="Organization ID" required pattern="[0-9a-fA-F\-]{36}" placeholder="36-character UUID"
              value={form.org_id} onChange={(e) => setForm({ ...form, org_id: e.target.value })} data-testid="conn-org" />
            <Field label="API token" type="password" autoComplete="off" required value={form.api_token}
              hint="Stored encrypted. It is never shown again. Use a token from a dedicated service account with the least privilege the workflows need."
              onChange={(e) => setForm({ ...form, api_token: e.target.value })} data-testid="conn-token" />
            {error && <p role="alert" className="text-body text-danger">{error}</p>}
            <div className="flex gap-2">
              <Button variant="primary" type="submit" disabled={create.isPending} data-testid="conn-save">Save</Button>
              <Button onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
