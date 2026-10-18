// SPDX-License-Identifier: Apache-2.0
// Runs for tests, as the API serves them (editor 4e-1): a list item; the RunFailed board's run, its graph and its
// steps. Made up, never a real tenant's (D24).
import type { Run, RunItem, RunStep, RunStepSummary, RunSteps } from "../lib/runs";
import type { GraphDoc, NodeType } from "../lib/workflows";
import { IF, LOOP, TRANSFORM, typeWith } from "./nodeTypes";

/** An instant on the person's own clock, today (16 October 2026) unless `day` says: what a page says of it doesn't
 * depend on the zone the tests run in. */
export const local = (h: number, m: number, s: number, ms = 0, day = 16) => new Date(2026, 9, day, h, m, s, ms).toISOString();

/** A live run a webhook started, succeeded, queued and started at `queuedAt`. */
export const item = (id: string, queuedAt: string | null, over: Partial<RunItem> = {}): RunItem => ({
  id, workflow_id: "w1", workflow_name: "AP offline triage", version_id: "v2", draft_snapshot_id: null, target_step_id: null,
  mode: "live", status: "succeeded", queued_at: queuedAt, started_at: queuedAt, ended_at: null, error: null, iterations: 0,
  kind: "run", parent_run_id: null, request: { status: "started", source: "webhook", reason: null }, started_by: null,
  cancel_requested_at: null, trigger: { source: "webhook", schedule: null, endpoint: "Mist events", rerun_of: null }, ...over,
});  // prettier-ignore

/** The RunFailed board: a live run a webhook started on version 2, which failed at `notify_noc`. */
export const FAILED_RUN: Run = {
  ...item("4a2b17e0-3b2d-4e5f-9a1b-2c3d4e5f6a7b", local(9, 41, 12), { status: "failed", ended_at: local(9, 41, 50) }),
  error: { code: "channel_not_found", message: "The channel wasn't found." },
  draft_revision: null, outcomes_recorded: true, parent: null, csv: null,
};  // prettier-ignore

/** Its steps' types: three actions of a made-up service (D24), an If and a Transform. */
export const RUN_TYPES: NodeType[] = [
  typeWith({}, { ref: "acme.get_device@1", type: "acme.get_device", title: "Get a device" }),
  typeWith({}, { ref: "acme.send_request@1", type: "acme.send_request", title: "Send a request" }),
  typeWith({}, { ref: "acme.post_message@1", type: "acme.post_message", title: "Post a message" }),
  IF,
  LOOP,
  TRANSFORM,
];

const step = (key: string, type: string, y: number, x = 0) => ({ id: `id-${key}`, key, type, position: { x, y } });
const to = (from: string, target: string, port = "out") => ({ from: { node: `id-${from}`, port }, to: { node: `id-${target}` } });
/** Version 2's graph: get_device, then is_down; true: open_case then notify_noc; false: log_recovery. */
export const FAILED_GRAPH: GraphDoc = {
  graph_format: 1,
  nodes: [
    step("get_device", "acme.get_device@1", 140), step("is_down", "flow.if@1", 280), step("open_case", "acme.send_request@1", 420),
    step("notify_noc", "acme.post_message@1", 560), step("log_recovery", "flow.transform@1", 420, 400),
  ],
  edges: [to("get_device", "is_down"), to("is_down", "open_case", "true"), to("open_case", "notify_noc"), to("is_down", "log_recovery", "false")],
};  // prettier-ignore

/** An attempt of a step in the failed run. */
export const attempt = (key: string, over: Partial<RunStep> = {}): RunStep => ({
  step_id: `id-${key}`, key, iteration_key: "", attempt: 1, status: "succeeded", started_at: local(9, 41, 13), ended_at: local(9, 41, 13, 400),
  input: null, output: null, error: null, outcome: null, cel_mode: null, effect: null, ...over,
});  // prettier-ignore
const summary = (key: string, type: string, over: Partial<RunStepSummary> = {}): RunStepSummary => ({
  step_id: `id-${key}`, key, type, origin: null, instances: 1, statuses: { succeeded: 1 }, ports: {}, final: attempt(key), ...over,
});  // prettier-ignore
/** Its steps in run order, as the server sums them up. */
export const FAILED_STEPS: RunSteps = {
  given: "input",
  steps: [
    summary("get_device", "acme.get_device@1", { origin: "sent" }),
    summary("is_down", "flow.if@1", { ports: { true: 1 }, final: attempt("is_down", { effect: { port: "true" } }) }),
    summary("open_case", "acme.send_request@1", { origin: "sent", final: attempt("open_case", { started_at: local(9, 41, 14), ended_at: local(9, 41, 15, 800) }) }),
    summary("notify_noc", "acme.post_message@1", {
      statuses: { failed: 1 },
      final: attempt("notify_noc", {
        attempt: 3, status: "failed", started_at: local(9, 41, 49), ended_at: local(9, 41, 50),
        error: { code: "channel_not_found", message: "The channel wasn't found." },
        input: { channel: "#noc-alert", text: "AP Paris-Opera-12 offline since 09:38", token: "[redacted]", blocks: "[truncated]" },
      }),
    }),
    summary("log_recovery", "flow.transform@1", { origin: "skipped", statuses: { skipped: 1 }, final: attempt("log_recovery", { status: "skipped" }) }),
  ],
};  // prettier-ignore

/** The RunLoop board: list_aps, then each_ap over its output; in its body, is_offline, and notify where it's true. */
export const LOOP_GRAPH: GraphDoc = {
  graph_format: 1,
  nodes: [
    step("list_aps", "acme.get_device@1", 140), { ...step("each_ap", "flow.loop@1", 280), config: { items: { $value: { kind: "cel", expr: "steps.list_aps.output" } } } },
    step("is_offline", "flow.if@1", 420), step("notify", "acme.post_message@1", 560),
  ],
  edges: [to("list_aps", "each_ap"), to("each_ap", "is_offline", "body"), to("is_offline", "notify", "true")],
};  // prettier-ignore
export const LOOP_TOTAL = 120;
/** Iteration n (from 0): is_offline took "true" on every seventh; notify ran there (the 4th iteration's failed), and
 * was skipped elsewhere. */
export function loopInstance(key: "is_offline" | "notify", n: number): RunStep {
  const on = n % 7 === 3 || n === 1;
  const at = local(14, 2, 10 + (n % 50), 0);
  if (key === "is_offline") return attempt(key, { iteration_key: `each_ap:${n}`, started_at: at, ended_at: at, effect: { port: on ? "true" : "false" } });
  if (!on) return attempt(key, { iteration_key: `each_ap:${n}`, status: "skipped", started_at: null, ended_at: null });
  return attempt(key, {
    iteration_key: `each_ap:${n}`, status: n === 3 ? "failed" : "succeeded", started_at: at, ended_at: local(14, 2, 10 + (n % 50), 900),
    error: n === 3 ? { code: "invalid_blocks", message: "Slack refused the message's blocks." } : null,
    input: { channel: "#noc-alert", text: `AP-Lobby-0${n} offline` },
  });  // prettier-ignore
}
export const LOOP_STEPS: RunSteps = {
  given: "input",
  steps: [
    summary("list_aps", "acme.get_device@1", { origin: "sent" }),
    summary("each_ap", "flow.loop@1", { final: attempt("each_ap", { started_at: local(14, 2, 10), ended_at: local(14, 4, 30), output: { count: LOOP_TOTAL } }) }),
    summary("is_offline", "flow.if@1", { instances: LOOP_TOTAL, statuses: { succeeded: LOOP_TOTAL }, ports: { true: 17, false: 103 }, final: null }),
    summary("notify", "acme.post_message@1", { origin: "sent", instances: LOOP_TOTAL, statuses: { succeeded: 14, failed: 3, skipped: 103 }, final: null }),
  ],
};  // prettier-ignore
