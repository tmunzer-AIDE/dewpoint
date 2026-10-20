// SPDX-License-Identifier: Apache-2.0
// Landing on a run just started (editor 4e-2; the run form design §5.2): the form gives way to the run's page, whose
// heading takes focus once it's shown. Only a page opened from a start is landed on, once: one opened any other way (a
// link, back and forward) keeps the browser's focus. Asked in an effect, never while rendering, so StrictMode's second
// pass finds it taken.
import { useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { RUN_TITLE } from "./useCancel";

let landing: string | null = null; // the run whose page is opening from a start

/** Marks the run whose page opens next as landed on from a start. */
export const landOn = (runId: string) => {
  landing = runId;
};

/** Opens a run just started, its heading to take focus once its page shows it. */
export function useLand(tenantId: string): (runId: string) => void {
  const navigate = useNavigate();
  return (runId) => {
    landOn(runId);
    void navigate({ to: "/t/$tenantId/runs/$runId", params: { tenantId, runId } });
  };
}

/** On a run's page: once its heading is `shown`, it takes focus if a start landed here. */
export function useLanded(runId: string, shown: boolean) {
  useEffect(() => {
    if (!shown || landing !== runId) return;
    landing = null;
    document.getElementById(RUN_TITLE)?.focus();
  }, [runId, shown]);
}
