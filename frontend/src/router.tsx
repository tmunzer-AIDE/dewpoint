// SPDX-License-Identifier: Apache-2.0
import { Navigate, Outlet, createRootRoute, createRoute, createRouter, useParams } from "@tanstack/react-router";
import { Shell } from "./components/Shell";
import { useSession } from "./lib/session";
import { useAfterAuth } from "./lib/useAfterAuth";
import { ConnectionsPage } from "./routes/Connections";
import { EditorPage } from "./routes/editor/Editor";
import { EnrollPage } from "./routes/Enroll";
import { LoginPage } from "./routes/Login";
import { MembersPage } from "./routes/Members";
import { MfaPage } from "./routes/Mfa";
import { SecurityPage } from "./routes/Security";
import { SettingsLayout } from "./routes/Settings";
import { TenantsPage } from "./routes/Tenants";
import { WorkflowsPage } from "./routes/Workflows";

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** The editor's 60 px icon rail at every width (outline §2): the canvas needs the room. */
    compactRail?: boolean;
  }
}

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

// A tenant's screens are keyed by the tenant: switching tenants mounts them afresh, so nothing typed for one tenant (a
// connection's token, a member's email) can be sent to another, and an answer still on its way for the old tenant
// lands on a screen that is gone rather than on the new tenant's form. The router alone reuses a screen whose route
// stays the same and only its parameters change.

function TenantHome() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId" });
  return <Navigate to="/t/$tenantId/workflows" params={{ tenantId }} />;
}

function Workflows() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/workflows" });
  const search = workflowsRoute.useSearch();
  return <WorkflowsPage key={tenantId} tenantId={tenantId} startNew={search.new === true} />;
}

function Editor() {
  const { tenantId, workflowId } = useParams({ from: "/app/t/$tenantId/workflows/$workflowId" });
  return <EditorPage key={`${tenantId}:${workflowId}`} tenantId={tenantId} workflowId={workflowId} />;
}

function Connections() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/connections" });
  return <ConnectionsPage key={tenantId} tenantId={tenantId} />;
}

function Settings() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/settings" });
  return <SettingsLayout key={tenantId} tenantId={tenantId} />;
}

function SettingsIndex() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/settings" });
  return <Navigate to="/t/$tenantId/settings/members" params={{ tenantId }} />;
}

function Members() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/settings/members" });
  return <MembersPage key={tenantId} tenantId={tenantId} />;
}

const rootRoute = createRootRoute({ component: Outlet });
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: Login });
const mfaRoute = createRoute({ getParentRoute: () => rootRoute, path: "/mfa", component: MfaPage });
const enrollRoute = createRoute({ getParentRoute: () => rootRoute, path: "/enroll", component: EnrollPage });
const appRoute = createRoute({ getParentRoute: () => rootRoute, id: "app", component: RequireActive });
const indexRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: () => <Navigate to="/tenants" /> });
const tenantsRoute = createRoute({ getParentRoute: () => appRoute, path: "/tenants", component: TenantsPage });
const securityRoute = createRoute({ getParentRoute: () => appRoute, path: "/account/security", component: SecurityPage });
const tenantHomeRoute = createRoute({ getParentRoute: () => appRoute, path: "/t/$tenantId", component: TenantHome });
const workflowsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/t/$tenantId/workflows",
  component: Workflows,
  validateSearch: (search: Record<string, unknown>): { new?: true } =>
    search.new === true || search.new === "true" ? { new: true } : {},
});
const editorRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/t/$tenantId/workflows/$workflowId",
  component: Editor,
  staticData: { compactRail: true },
});
const connectionsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/t/$tenantId/connections",
  component: Connections,
});

const settingsRoute = createRoute({ getParentRoute: () => appRoute, path: "/t/$tenantId/settings", component: Settings });
const settingsIndexRoute = createRoute({ getParentRoute: () => settingsRoute, path: "/", component: SettingsIndex });
const membersRoute = createRoute({ getParentRoute: () => settingsRoute, path: "members", component: Members });

/** The app's routes; the router below serves them from the browser's history (tests serve them from memory). */
export const routeTree = rootRoute.addChildren([
  loginRoute,
  mfaRoute,
  enrollRoute,
  appRoute.addChildren([
    indexRoute,
    tenantsRoute,
    securityRoute,
    tenantHomeRoute,
    workflowsRoute,
    editorRoute,
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
