// SPDX-License-Identifier: Apache-2.0
// Settings → Members & roles (D11; the design names the tab in 1i, the tab itself is built in its grammar). Anyone in
// the tenant reads the list; admins and owners add, change and remove members. The API decides every write.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Field, Select } from "../components/Field";
import { LoadError } from "../components/LoadError";
import { Table, Td, Th } from "../components/Table";
import { ApiError, client, ok, type Schemas } from "../lib/client";
import { useDocumentTitle } from "../lib/title";

type Member = Schemas["MemberOut"];
type Role = Member["role"];
const ROLES: Role[] = ["owner", "admin", "editor", "operator", "viewer"];

const MESSAGES: Record<string, string> = {
  user_not_found: "No Dewpoint account has that email. A platform admin creates accounts.",
  last_owner: "A tenant keeps at least one owner: make someone else owner first.",
  owner_only: "Only an owner can give or take the owner role.",
  forbidden: "You don't have permission to manage members.",
};
const message = (e: unknown) => (e instanceof ApiError && MESSAGES[e.code]) || "That didn't work. Try again.";

export function MembersPage({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const path = { tenant_id: tenantId };
  const tenant = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}", { params: { path } })),
  });
  const members = useQuery({
    queryKey: ["members", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/members", { params: { path } })),
  });
  const canManage = tenant.data?.role === "admin" || tenant.data?.role === "owner";
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["members", tenantId] });
  const heading = useRef<HTMLHeadingElement>(null);
  useDocumentTitle("Members & roles");

  const add = useMutation({
    mutationFn: () => ok(client.POST("/api/v1/t/{tenant_id}/members", { params: { path }, body: { email, role } })),
    onMutate: () => setError(null),
    onSuccess: async () => {
      setEmail("");
      await refresh();
    },
    onError: (e) => setError(message(e)),
  });
  const change = useMutation({
    mutationFn: (m: { user_id: string; role: Role }) =>
      ok(client.PATCH("/api/v1/t/{tenant_id}/members/{user_id}", {
        params: { path: { ...path, user_id: m.user_id } },
        body: { role: m.role },
      })),
    onMutate: () => setError(null),
    onSettled: refresh,
    onError: (e) => setError(message(e)),
  });
  const remove = useMutation({
    mutationFn: (user_id: string) =>
      ok(client.DELETE("/api/v1/t/{tenant_id}/members/{user_id}", { params: { path: { ...path, user_id } } })),
    onMutate: () => setError(null),
    // The row and its button are gone once the list is fresh: focus goes to the list's heading, however the dialog
    // closed (the browser may close it on a second Escape even while it holds).
    onSuccess: async () => {
      setRemoving(null);
      await refresh();
      heading.current?.focus();
    },
    onError: (e) => {
      setRemoving(null);
      setError(message(e));
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    add.mutate();
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div>
        <h2 ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Members</h2>
        <p className="mt-0.5 text-small text-muted">
          Who can use this tenant, and what they can do. Accounts are created by a platform admin.
        </p>
      </div>
      {error && <p role="alert" className="text-body text-danger">{error}</p>}
      {members.isError ? <LoadError what="The members" /> : <Table label="Members" className="max-w-3xl">
        <thead>
          <tr><Th>Email</Th><Th>Role</Th>{canManage && <Th><span className="sr-only">Actions</span></Th>}</tr>
        </thead>
        <tbody>
          {members.data?.map((m) => (
            <tr key={m.user_id}>
              <Td>{m.email}</Td>
              <Td>
                {canManage ? (
                  <select
                    aria-label={`Role of ${m.email}`}
                    value={m.role}
                    disabled={change.isPending}
                    onChange={(e) => change.mutate({ user_id: m.user_id, role: e.target.value as Role })}
                    className="min-h-8 rounded-md border border-line-control bg-surface px-2 text-small text-ink"
                  >
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                ) : (
                  m.role
                )}
              </Td>
              {canManage && (
                <Td className="text-right">
                  <Button size="sm" variant="danger-outline" aria-label={`Remove ${m.email}`} onClick={() => setRemoving(m)}>
                    Remove
                  </Button>
                </Td>
              )}
            </tr>
          ))}
        </tbody>
      </Table>}
      {canManage && (
        <form onSubmit={submit} aria-label="Add a member" className="flex max-w-3xl flex-wrap items-end gap-3 rounded-lg border border-line bg-surface p-4">
          <div className="min-w-0 grow basis-48">
            <Field label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="min-w-0 basis-44">
            <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </Select>
          </div>
          <Button variant="primary" type="submit" disabled={add.isPending}>Add member</Button>
        </form>
      )}
      <ConfirmDialog
        open={removing !== null}
        title="Remove a member"
        confirmLabel="Remove"
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.user_id)}
        onCancel={() => setRemoving(null)}
      >
        {removing?.email} loses access to {tenant.data?.name ?? "this tenant"} at once.
      </ConfirmDialog>
    </div>
  );
}
