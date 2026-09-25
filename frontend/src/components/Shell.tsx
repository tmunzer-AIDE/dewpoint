// SPDX-License-Identifier: Apache-2.0
import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { onStepUpRequired } from "../lib/events";
import { signOut } from "../lib/signOut";
import { authenticatePasskey } from "../lib/webauthn";
import { Button } from "./Button";
import { TenantSwitcher } from "./TenantSwitcher";

function Mark() {
  return (
    <svg width="20" height="20" viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <path d="M13 3C13 3 5 11.5 5 16.5a8 8 0 0 0 16 0C21 11.5 13 3 13 3Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

export function Shell() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const params = useParams({ strict: false });
  const [stepUp, setStepUp] = useState(false);
  const [stepUpError, setStepUpError] = useState<string | null>(null);
  useEffect(() => onStepUpRequired(() => setStepUp(true)), []);

  const [signOutError, setSignOutError] = useState<string | null>(null);

  async function handleSignOut() {
    setSignOutError(null);
    if ((await signOut()) === "failed") {
      // The server session may still be valid: never pretend otherwise.
      setSignOutError("Sign-out failed. You are still signed in; check your connection and try again.");
      return;
    }
    qc.clear();
    await navigate({ to: "/login" });
  }

  async function doStepUp() {
    setStepUpError(null);
    try {
      await authenticatePasskey("stepup");
      setStepUp(false);
      await qc.invalidateQueries();
    } catch {
      setStepUpError("That passkey could not be verified.");
    }
  }

  const nav = "rounded-md px-3 py-2 text-sm text-muted hover:bg-surface-2 data-[status=active]:bg-accent-soft data-[status=active]:text-accent-ink";
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-14 items-center gap-4 border-b border-line bg-surface px-4">
        <span className="flex items-center gap-2 font-semibold text-accent">
          <Mark /> <span className="text-ink">Dewpoint</span>
        </span>
        <TenantSwitcher />
        <div className="grow" />
        <Link to="/account/security" className="text-sm text-muted hover:text-ink">Security</Link>
        <Button onClick={() => void handleSignOut()}>Sign out</Button>
      </header>
      {signOutError && (
        <div role="alert" className="border-b border-danger bg-surface-2 px-4 py-3 text-sm text-danger">
          {signOutError}
        </div>
      )}
      {stepUp && (
        <div role="alert" className="flex items-center gap-3 border-b border-line bg-surface-2 px-4 py-3 text-sm">
          <span>This tenant requires a passkey. Confirm with your passkey to continue.</span>
          <Button variant="primary" onClick={() => void doStepUp()}>Use passkey</Button>
          {stepUpError && <span className="text-danger">{stepUpError}</span>}
        </div>
      )}
      <div className="flex grow">
        <nav aria-label="Main" className="flex w-52 flex-col gap-1 border-r border-line bg-surface p-3">
          {params.tenantId && (
            <Link to="/t/$tenantId/connections" params={{ tenantId: params.tenantId }} className={nav}>
              Connections
            </Link>
          )}
          <Link to="/tenants" className={nav}>Tenants</Link>
        </nav>
        <main className="grow">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
