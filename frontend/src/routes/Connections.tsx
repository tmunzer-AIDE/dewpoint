// SPDX-License-Identifier: Apache-2.0
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { StatusBadge } from "../components/StatusBadge";
import { ApiError, api } from "../lib/api";

interface Conn {
  id: string; type: string; name: string; revision: number; config: { cloud: string; org_id: string };
  secret_set: boolean; status: "ok" | "error" | "unverified"; status_detail: string; privilege: string | null;
}
interface ConnType { key: string; label: string; clouds?: Record<string, string> }

export function ConnectionsPage({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const base = `/api/v1/t/${tenantId}/connections`;
  const list = useQuery({ queryKey: ["connections", tenantId], queryFn: () => api<Conn[]>("GET", base) });
  const types = useQuery({ queryKey: ["connection-types"], queryFn: () => api<ConnType[]>("GET", "/api/v1/connection-types") });
  const clouds = types.data?.find((t) => t.key === "mist")?.clouds ?? {};
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", cloud: "global_01", org_id: "", api_token: "" });
  const [error, setError] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["connections", tenantId] });

  const create = useMutation({
    mutationFn: () => api<Conn>("POST", base, {
      type: "mist", name: form.name, config: { cloud: form.cloud, org_id: form.org_id },
      secret: { api_token: form.api_token },
    }),
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
    mutationFn: (id: string) => api<Conn>("POST", `${base}/${id}/verify`),
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
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Connections</h1>
        <Button variant="primary" onClick={() => setOpen(true)} data-testid="conn-add">Add Mist connection</Button>
      </header>
      {verifyError && <p role="alert" className="text-sm text-danger">{verifyError}</p>}
      <table className="w-full border-collapse rounded-lg border border-line bg-surface text-sm">
        <thead className="bg-surface-2 text-left text-muted">
          <tr><th className="p-3">Name</th><th className="p-3">Cloud</th><th className="p-3">Org ID</th>
            <th className="p-3">Status</th><th className="p-3"><span className="sr-only">Actions</span></th></tr>
        </thead>
        <tbody>
          {list.data?.map((c) => (
            <tr key={c.id} className="border-t border-line" data-testid="conn-row">
              <td className="p-3 font-medium">{c.name}</td>
              <td className="p-3 font-mono text-[13px]">{clouds[c.config.cloud] ?? c.config.cloud}</td>
              <td className="p-3 font-mono text-[13px]">{c.config.org_id}</td>
              <td className="p-3"><StatusBadge status={c.status} detail={c.status_detail} privilege={c.privilege} /></td>
              <td className="p-3 text-right">
                <Button onClick={() => verify.mutate(c.id)} disabled={verify.isPending}>Verify</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open && (
        <form role="dialog" aria-label="Add Mist connection" className="flex max-w-lg flex-col gap-4 rounded-lg border border-line bg-surface p-5"
          onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
          <Field label="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="conn-name" />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="cloud" className="text-sm font-semibold">Mist cloud</label>
            <select id="cloud" className="min-h-11 rounded-lg border border-line-strong bg-surface px-3" value={form.cloud}
              onChange={(e) => setForm({ ...form, cloud: e.target.value })} data-testid="conn-cloud">
              {Object.entries(clouds).map(([k, host]) => <option key={k} value={k}>{host}</option>)}
            </select>
          </div>
          <Field label="Organization ID" required pattern="[0-9a-fA-F-]{36}" value={form.org_id}
            onChange={(e) => setForm({ ...form, org_id: e.target.value })} data-testid="conn-org" />
          <Field label="API token" type="password" autoComplete="off" required value={form.api_token}
            hint="Stored encrypted. It is never shown again." onChange={(e) => setForm({ ...form, api_token: e.target.value })}
            data-testid="conn-token" />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div className="flex gap-2">
            <Button variant="primary" type="submit" disabled={create.isPending} data-testid="conn-save">Save</Button>
            <Button type="button" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </form>
      )}
    </section>
  );
}
