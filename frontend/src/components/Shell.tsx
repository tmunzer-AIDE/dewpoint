// SPDX-License-Identifier: Apache-2.0
// The app's frame, as designed (screen 1a): the navy rail with the wordmark and the main navigation, a header with the
// tenant switcher, Security and Sign out, and the page.
import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { onStepUpRequired } from "../lib/events";
import { signOut } from "../lib/signOut";
import { authenticatePasskey } from "../lib/webauthn";
import { Button } from "./Button";
import { CommandPalette } from "./CommandPalette";
import { ConnectionsIcon } from "./icons";
import { Wordmark } from "./Mark";
import { TenantSwitcher } from "./TenantSwitcher";

// The current item stands apart from a hovered one by weight, ink and a 1.5:1 background step (ledger, ruling 18).
const ITEM = "flex items-center gap-2.5 rounded-md px-3 py-2 text-body text-rail-ink";
const CURRENT = "bg-rail-active font-semibold text-rail-ink-strong";
const INACTIVE = "hover:bg-rail-line";

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

  return (
    <div className="grid min-h-screen grid-cols-[var(--rail-w)_minmax(0,1fr)] grid-rows-[var(--header-h)_1fr]">
      <div data-surface="rail" className="row-span-2 flex flex-col gap-0.5 bg-rail px-3 py-4">
        <span className="px-2 pt-2 pb-5">
          <Wordmark />
        </span>
        <nav aria-label="Main" className="flex flex-col gap-0.5">
          {params.tenantId && (
            <Link
              to="/t/$tenantId/connections"
              params={{ tenantId: params.tenantId }}
              className={ITEM}
              activeProps={{ className: CURRENT }}
              inactiveProps={{ className: INACTIVE }}
            >
              <ConnectionsIcon />
              Connections
            </Link>
          )}
        </nav>
      </div>
      <header className="col-start-2 flex items-center gap-4 border-b border-line bg-surface px-5">
        <TenantSwitcher />
        <CommandPalette />
        <div className="grow" />
        <Link to="/account/security" className="text-body text-muted hover:text-ink">Security</Link>
        <Button size="md" onClick={() => void handleSignOut()}>Sign out</Button>
      </header>
      <main className="col-start-2 flex min-w-0 flex-col">
        {signOutError && (
          <div role="alert" className="m-6 mb-0 rounded-lg border border-danger bg-danger-bg px-3 py-2 text-small text-ink">
            {signOutError}
          </div>
        )}
        {stepUp && (
          <div role="alert" className="m-6 mb-0 flex items-center gap-3 rounded-lg border border-warn-line bg-warn-bg px-3 py-2 text-small text-warn-ink">
            <span>This tenant requires a passkey. Confirm with your passkey to continue.</span>
            <Button size="sm" variant="primary" onClick={() => void doStepUp()}>Use passkey</Button>
            {stepUpError && <span className="text-danger">{stepUpError}</span>}
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
