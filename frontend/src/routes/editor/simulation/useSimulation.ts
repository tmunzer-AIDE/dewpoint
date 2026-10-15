// SPDX-License-Identifier: Apache-2.0
// The editor's simulation (4d-1c; the simulation design §7.1, §7.2; the Lifecycle board): one at a time, from this
// editor. A submit is frozen with its key; its answer lost, "Check again" sends that same request, which can't start a
// second time while the first is kept. Once admitted it's read where it is, at 1 s, backing off to 5 s, paused while
// the tab is hidden; a failed read keeps the last state known, as of when it was read. After a reload there is no
// frozen request: the person's latest simulation of the workflow is read, labelled as exactly that.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "../../../lib/client";
import {
  ENDED, cancelSimulation, latestSimulationQuery, phaseOf, pollEvery, sendSimulation, simulationStateQuery,
  simulationStepsQuery, type Frozen, type Phase, type SimulationRequest, type SimulationState, type SimulationSteps,
} from "../../../lib/simulations";  // prettier-ignore

/** Where the editor's own part of a simulation is: before an answer, or after one. */
export type Local =
  | { kind: "idle" }
  | { kind: "submitting"; frozen: Frozen }
  | { kind: "unknown"; frozen: Frozen } // its answer was lost: it may have started
  | { kind: "refused"; frozen: Frozen; error: ApiError } // admission said no, in the server's words
  | { kind: "admitted"; frozen: Frozen | null; request: SimulationRequest; latest: boolean };

export interface SimulationSession {
  local: Local;
  state: SimulationState | null; // the newest read
  steps: SimulationSteps | null; // its steps, read with it
  phase: Phase | null;
  /** Simulate waits: a submit, an answer lost, or a simulation not ended (§7.1). */
  busy: boolean;
  /** The last read failed: what's shown is as of `asOf` (§7.2). */
  readFailed: boolean;
  /** The last cancel didn't go through (no answer, or refused): the person is told, and may try again. */
  cancelFailed: boolean;
  asOf: number | null;
  start: (frozen: Frozen) => Promise<void>;
  checkAgain: () => Promise<void>;
  cancel: () => Promise<"cancelled" | "requested" | null>;
  readAgain: () => void;
}

/** Whether a request's outcome is unknown: no answer reached the editor, or a 5xx came in the API's place. The API's
 * own 503 says why, in its code (the production gate, no current build): a refusal, known. */
const uncertain = (e: unknown) => !(e instanceof ApiError) || (e.status >= 500 && !(e.status === 503 && e.code !== "http_error"));

export function useSimulation(tenantId: string, workflowId: string): SimulationSession {
  const qc = useQueryClient();
  const [local, setLocal] = useState<Local>({ kind: "idle" });
  const latest = useQuery({ ...latestSimulationQuery(tenantId, workflowId), enabled: local.kind === "idle" });
  useEffect(() => {
    const found = latest.data;
    if (found) setLocal((l) => (l.kind === "idle" ? { kind: "admitted", frozen: null, request: found, latest: true } : l));
  }, [latest.data]);

  const requestId = local.kind === "admitted" ? local.request.id : null;
  const read = useQuery({
    ...simulationStateQuery(tenantId, workflowId, requestId ?? ""),
    enabled: requestId !== null,
    refetchInterval: (q) => (q.state.data && ENDED.has(phaseOf(q.state.data)) ? false : pollEvery(q.state.dataUpdateCount + q.state.errorUpdateCount)),
  });
  const state = requestId !== null ? (read.data ?? null) : null;
  const phase = state ? phaseOf(state) : null;
  const ended = phase !== null && ENDED.has(phase);
  const stepsRead = useQuery({
    ...simulationStepsQuery(tenantId, workflowId, requestId ?? ""),
    enabled: requestId !== null && phase !== null && phase !== "refused" && phase !== "dead",
    refetchInterval: (q) => (ended ? false : pollEvery(q.state.dataUpdateCount + q.state.errorUpdateCount)),
  });
  // Its steps as they were when it ended: read once more after the end is known.
  useEffect(() => {
    if (ended && requestId !== null) void qc.invalidateQueries({ queryKey: ["simulation-steps", tenantId, workflowId, requestId] });
  }, [ended, requestId, qc, tenantId, workflowId]);

  const send = useCallback(
    async (frozen: Frozen) => {
      setLocal({ kind: "submitting", frozen });
      setCancelFailed(false);
      try {
        const request = await sendSimulation(tenantId, workflowId, frozen);
        setLocal({ kind: "admitted", frozen, request, latest: false });
      } catch (e) {
        setLocal(uncertain(e) ? { kind: "unknown", frozen } : { kind: "refused", frozen, error: e as ApiError });
      }
    },
    [tenantId, workflowId],
  );
  // The same request again: its answer lost, or refused (admission rolls a refusal back, so its key is free).
  const checkAgain = useCallback(async () => {
    if (local.kind === "unknown" || local.kind === "refused") await send(local.frozen);
  }, [local, send]);
  const [cancelFailed, setCancelFailed] = useState(false);
  const cancel = useCallback(async () => {
    if (requestId === null) return null;
    let done: "cancelled" | "requested";
    try {
      done = await cancelSimulation(tenantId, requestId);
    } catch {
      setCancelFailed(true);
      return null;
    }
    setCancelFailed(false);
    await qc.invalidateQueries({ queryKey: ["simulation", tenantId, workflowId, requestId] });
    return done;
  }, [qc, requestId, tenantId, workflowId]);
  const readAgain = useCallback(() => void read.refetch(), [read]);

  const busy = local.kind === "submitting" || local.kind === "unknown" || (local.kind === "admitted" && !ended);
  return useMemo(
    () => ({
      local, state, steps: requestId !== null ? (stepsRead.data ?? null) : null, phase, busy,
      readFailed: read.isRefetchError, asOf: read.dataUpdatedAt || null, cancelFailed, start: send, checkAgain, cancel, readAgain,
    }),
    [local, state, requestId, stepsRead.data, phase, busy, read.isRefetchError, read.dataUpdatedAt, cancelFailed, send, checkAgain, cancel, readAgain],
  );  // prettier-ignore
}
