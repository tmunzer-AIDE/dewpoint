// SPDX-License-Identifier: Apache-2.0
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { client, ok, type Schemas } from "../lib/client";

export type TenantRow = Schemas["TenantOut"];

// Pointer hover and keyboard focus both highlight; keyboard focus also draws the global focus ring.
const ITEM = "flex cursor-pointer justify-between gap-4 rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink";

export function TenantSwitcher() {
  const navigate = useNavigate();
  const params = useParams({ strict: false });
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: () => ok(client.GET("/api/v1/tenants")) });
  const current = tenants.data?.find((t) => t.id === params.tenantId);
  return (
    // Non-modal: a modal menu locks scrolling by injecting a <style>, which the CSP refuses, and hides the page from
    // assistive technology while it stays focusable (D23; the 4a browser gate caught both).
    <Dropdown.Root modal={false}>
      <Dropdown.Trigger
        data-testid="tenant-switcher"
        className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-body text-ink hover:bg-surface-hover"
      >
        {current?.name ?? "Choose tenant"}
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5 6 7.5l3-3" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
        </svg>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content sideOffset={6} align="start" className="min-w-56 rounded-lg border border-line bg-surface p-1 shadow-dialog">
          {tenants.data?.map((t) => (
            <Dropdown.Item
              key={t.id}
              onSelect={() => void navigate({ to: "/t/$tenantId/connections", params: { tenantId: t.id } })}
              className={ITEM}
            >
              <span>{t.name}</span>
              <span className="text-muted">{t.role}</span>
            </Dropdown.Item>
          ))}
          {tenants.data?.length === 0 && <div className="px-3 py-2 text-body text-muted">No tenants yet</div>}
          <Dropdown.Separator className="my-1 h-px bg-line" />
          <Dropdown.Item onSelect={() => void navigate({ to: "/tenants" })} className={ITEM}>
            All tenants
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}
