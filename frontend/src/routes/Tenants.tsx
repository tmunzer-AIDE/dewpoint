// SPDX-License-Identifier: Apache-2.0
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { Table, Td, Th } from "../components/Table";
import type { TenantRow } from "../components/TenantSwitcher";
import { ApiError, api } from "../lib/api";
import { useSession } from "../lib/session";

export function TenantsPage() {
  const qc = useQueryClient();
  const session = useSession();
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: () => api<TenantRow[]>("GET", "/api/v1/tenants") });
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api<TenantRow>("POST", "/api/v1/tenants", { name, slug }),
    onSuccess: async () => {
      setName("");
      setSlug("");
      await qc.invalidateQueries({ queryKey: ["tenants"] });
    },
    onError: (e) =>
      setError(e instanceof ApiError && e.code === "slug_taken" ? "That slug is already used." : "Check the fields and try again."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    create.mutate();
  }

  return (
    <section className="flex flex-col gap-6 p-6">
      <h1 className="text-h1 font-semibold">Tenants</h1>
      <Table className="max-w-3xl">
        <thead>
          <tr><Th>Name</Th><Th>Slug</Th><Th>Your role</Th></tr>
        </thead>
        <tbody>
          {tenants.data?.map((t) => (
            <tr key={t.id}>
              <Td>
                <Link to="/t/$tenantId/connections" params={{ tenantId: t.id }} className="font-medium text-accent-ink">
                  {t.name}
                </Link>
              </Td>
              <Td className="font-mono text-small">{t.slug}</Td>
              <Td>{t.role}</Td>
            </tr>
          ))}
          {tenants.data?.length === 0 && (
            <tr><Td colSpan={3} className="text-muted">You're not a member of any tenant yet.</Td></tr>
          )}
        </tbody>
      </Table>
      {session.data?.user.is_platform_admin && (
        <form onSubmit={submit} className="flex max-w-lg flex-col gap-4 rounded-lg border border-line bg-surface p-5">
          <h2 className="text-body-lg font-semibold">Create tenant</h2>
          <Field label="Name" required value={name} onChange={(e) => setName(e.target.value)} data-testid="tenant-name" />
          <Field label="Slug" required pattern="[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]" hint="Lowercase letters, digits and dashes."
            value={slug} onChange={(e) => setSlug(e.target.value)} data-testid="tenant-slug" />
          {error && <p role="alert" className="text-body text-danger">{error}</p>}
          <Button variant="primary" type="submit" disabled={create.isPending} className="self-start" data-testid="tenant-create">Create tenant</Button>
        </form>
      )}
    </section>
  );
}
