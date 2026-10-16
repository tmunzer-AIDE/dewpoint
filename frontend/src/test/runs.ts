// SPDX-License-Identifier: Apache-2.0
// Runs for tests, as the API serves them (editor 4e-1): a list item, made up, never a real tenant's (D24).
import type { RunItem } from "../lib/runs";

/** A live run a webhook started, succeeded, queued and started at `queuedAt`. */
export const item = (id: string, queuedAt: string | null, over: Partial<RunItem> = {}): RunItem => ({
  id, workflow_id: "w1", workflow_name: "AP offline triage", version_id: "v2", draft_snapshot_id: null, target_step_id: null,
  mode: "live", status: "succeeded", queued_at: queuedAt, started_at: queuedAt, ended_at: null, error: null, iterations: 0,
  kind: "run", parent_run_id: null, request: { status: "started", source: "webhook", reason: null }, started_by: null,
  cancel_requested_at: null, trigger: { source: "webhook", schedule: null, endpoint: "Mist events", rerun_of: null }, ...over,
});  // prettier-ignore
