// SPDX-License-Identifier: Apache-2.0
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

/** Route to the right screen for a session state returned by any sign-in step. */
export function useAfterAuth(): (state: string) => Promise<void> {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return async (state: string) => {
    await qc.invalidateQueries({ queryKey: ["session"] });
    if (state === "mfa_pending") await navigate({ to: "/mfa" });
    else if (state === "enroll_required") await navigate({ to: "/enroll" });
    else await navigate({ to: "/tenants" });
  };
}
