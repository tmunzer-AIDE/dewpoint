// SPDX-License-Identifier: Apache-2.0
// Reading a run while it runs (editor 4e-1; the runs design §5.3): its state every second, backing off to every 5 s
// (as a simulation's, `pollEvery`), paused while the tab is hidden; its steps' summary with it, at most every 5 s. Once
// it ends, its steps are read then, and both once more 5 s later: step rows and sub-runs can still settle. After that,
// only on focus or a reload. Its end is said once, through the shell's live region (§5.6).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { announce } from "../../lib/announce";
import { isEnded, runQuery, runStepsQuery } from "../../lib/runs";
import { RUN_STATUS } from "../../lib/runStatus";
import { pollEvery } from "../../lib/simulations";

const SUMMARY_EVERY = 5000;
const SETTLE = 5000; // the once-more read after the end

export function useRunReads(tenantId: string, runId: string) {
  const run = useQuery({
    ...runQuery(tenantId, runId),
    refetchInterval: (q) => (q.state.data === undefined || isEnded(q.state.data.status) ? false : pollEvery(q.state.dataUpdateCount + q.state.errorUpdateCount)),
  });
  const ended = run.data !== undefined && isEnded(run.data.status);
  const steps = useQuery({ ...runStepsQuery(tenantId, runId), enabled: run.data !== undefined, refetchInterval: ended ? false : SUMMARY_EVERY });
  const status = run.data?.status;
  const was = useRef(status);
  const { refetch: readRun } = run;
  const { refetch: readSteps } = steps;
  useEffect(() => {
    const before = was.current;
    was.current = status;
    // Only an end seen here: a run already ended when the page opened is read as it is.
    if (status === undefined || before === undefined || isEnded(before) || !isEnded(status)) return;
    announce(`Run ended: ${RUN_STATUS[status].word.toLowerCase()}`);
    void readSteps();
    const later = setTimeout(() => {
      void readRun();
      void readSteps();
    }, SETTLE);
    return () => clearTimeout(later);
  }, [status, readRun, readSteps]);
  return { run, steps };
}
