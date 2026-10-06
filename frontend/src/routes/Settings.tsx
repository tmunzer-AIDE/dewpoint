// SPDX-License-Identifier: Apache-2.0
// Settings, as in screen 1i: the tenant's name, then its tabs as links (each tab is its own page). In 4a: Members &
// roles; Webhook endpoints arrives with 4c, Notification channels with sub-project 3, Service grants with 5 (D11).
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "@tanstack/react-router";
import { client, ok } from "../lib/client";

const TAB = "-mb-px border-b-2 px-3 py-2 text-body";

export function SettingsLayout({ tenantId }: { tenantId: string }) {
  const tenant = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}", { params: { path: { tenant_id: tenantId } } })),
  });
  return (
    <section className="flex flex-col gap-3.5 p-6">
      <h1 className="text-h1 font-semibold">Settings{tenant.data ? ` · ${tenant.data.name}` : ""}</h1>
      <nav aria-label="Settings" className="flex gap-1 overflow-x-auto border-b border-line">
        <Link
          to="/t/$tenantId/settings/members"
          params={{ tenantId }}
          className={TAB}
          activeProps={{ className: "border-accent font-semibold text-ink" }}
          inactiveProps={{ className: "border-transparent text-muted hover:text-ink" }}
        >
          Members &amp; roles
        </Link>
      </nav>
      <Outlet />
    </section>
  );
}
