// SPDX-License-Identifier: Apache-2.0
import { Navigate, Outlet, createRootRoute, createRoute, createRouter, useParams } from "@tanstack/react-router";
import { Shell } from "./components/Shell";
import { useSession } from "./lib/session";
import { useAfterAuth } from "./lib/useAfterAuth";
import { ConnectionsPage } from "./routes/Connections";
import { EnrollPage } from "./routes/Enroll";
import { LoginPage } from "./routes/Login";
import { MembersPage } from "./routes/Members";
import { MfaPage } from "./routes/Mfa";
import { SecurityPage } from "./routes/Security";
import { SettingsLayout } from "./routes/Settings";
import { TenantsPage } from "./routes/Tenants";

/** Sends each session state to its screen; renders children only for fully signed-in sessions. */
function RequireActive() {
  const session = useSession();
  if (session.isPending) return <p className="p-6 text-body text-muted">Loading…</p>;
  if (!session.data) return <Navigate to="/login" />;
  if (session.data.state === "mfa_pending") return <Navigate to="/mfa" />;
  if (session.data.state === "enroll_required") return <Navigate to="/enroll" />;
  return <Shell />;
}

function Login() {
  const afterAuth = useAfterAuth();
  return <LoginPage navigateByState={(state) => void afterAuth(state)} />;
}

function Connections() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/connections" });
  return <ConnectionsPage tenantId={tenantId} />;
}

function Settings() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/settings" });
  return <SettingsLayout tenantId={tenantId} />;
}

function SettingsIndex() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/settings" });
  return <Navigate to="/t/$tenantId/settings/members" params={{ tenantId }} />;
}

function Members() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/settings/members" });
  return <MembersPage tenantId={tenantId} />;
}

const rootRoute = createRootRoute({ component: Outlet });
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: Login });
const mfaRoute = createRoute({ getParentRoute: () => rootRoute, path: "/mfa", component: MfaPage });
const enrollRoute = createRoute({ getParentRoute: () => rootRoute, path: "/enroll", component: EnrollPage });
const appRoute = createRoute({ getParentRoute: () => rootRoute, id: "app", component: RequireActive });
const indexRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: () => <Navigate to="/tenants" /> });
const tenantsRoute = createRoute({ getParentRoute: () => appRoute, path: "/tenants", component: TenantsPage });
const securityRoute = createRoute({ getParentRoute: () => appRoute, path: "/account/security", component: SecurityPage });
const connectionsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/t/$tenantId/connections",
  component: Connections,
});

const settingsRoute = createRoute({ getParentRoute: () => appRoute, path: "/t/$tenantId/settings", component: Settings });
const settingsIndexRoute = createRoute({ getParentRoute: () => settingsRoute, path: "/", component: SettingsIndex });
const membersRoute = createRoute({ getParentRoute: () => settingsRoute, path: "members", component: Members });

const routeTree = rootRoute.addChildren([
  loginRoute,
  mfaRoute,
  enrollRoute,
  appRoute.addChildren([
    indexRoute,
    tenantsRoute,
    securityRoute,
    connectionsRoute,
    settingsRoute.addChildren([settingsIndexRoute, membersRoute]),
  ]),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
