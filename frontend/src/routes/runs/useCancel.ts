// SPDX-License-Identifier: Apache-2.0
// Cancelling a run (editor 4e-1; the runs design §5.3; the RunRunning board). A live run asks first: what it already
// did isn't undone. A simulation cancels at once. Once sent, the run is read again: it says the cancel is requested
// until the server confirms it, and focus goes to its name, the Cancel it was on gone. A cancel that didn't go through
// says so, and is offered again.
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { announce } from "../../lib/announce";
import { cancelRun, runQuery } from "../../lib/runs";

export const RUN_TITLE = "run-title"; // the bar's heading, where focus goes once a cancel is sent

export function useCancel(tenantId: string, runId: string, live: boolean) {
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "asking" | "sending" | "failed">("idle");
  async function send() {
    setState("sending");
    try {
      const answer = await cancelRun(tenantId, runId);
      await qc.invalidateQueries({ queryKey: runQuery(tenantId, runId).queryKey });
      setState("idle");
      if (answer.cancel === "requested") announce("Cancel requested. It's shown as cancelled once the server confirms it.");
      document.getElementById(RUN_TITLE)?.focus();
    } catch {
      setState("failed");
    }
  }
  return {
    state,
    /** Asks first for a live run; a simulation's is sent at once. */
    ask: () => (live ? setState("asking") : void send()),
    send: () => void send(),
    keep: () => setState("idle"),
  };
}
