// SPDX-License-Identifier: Apache-2.0
// Triggers for tests, as the API serves them: a schedule, an endpoint, a binding, and a webhook trigger type keyed as
// Mist's is (`mist.webhook`, which the UI names a sender by) whose topics are made-up envelopes, never Mist's own
// schemas (D24).
import type { Endpoint, Schedule, TriggerType, WorkflowBinding } from "../lib/triggers";

const event = (fields: Record<string, unknown>, required: string[] = []) => ({ type: "object", properties: fields, required });

/** A topic's shape as a trigger type serves it: `{topic, events}`, the topic fixed, the events typed by `$defs`. */
export const envelope = (topic: string, fields: Record<string, unknown>, required: string[] = []) => ({
  type: "object",
  properties: {
    topic: { type: "string", const: topic },
    events: { type: "array", items: { $ref: "#/$defs/event" } },
  },
  required: ["events", "topic"],
  $defs: { event: event(fields, required) },
});

export const DEVICE_EVENTS = envelope(
  "device-events",
  { ap_name: { type: "string" }, device_name: { type: "string" }, ev_type: { type: "string" }, mac: { type: "string" }, timestamp: { type: "number" } },
  ["timestamp"],
);

export const MIST: TriggerType = {
  key: "mist.webhook", label: "Mist webhook", plugin: "mist",
  endpoint: { auth: "bearer", events_pointer: null, id_source: "none" },
  topic_pointer: "/topic",
  topics: {
    alarms: envelope("alarms", { type: { type: "string" } }),
    "device-events": DEVICE_EVENTS,
    "device-updowns": envelope("device-updowns", { mac: { type: "string" } }),
  },
};  // prettier-ignore

export const SCHEDULE: Schedule = {
  id: "s1", workflow_id: "w1", cron: "0 7 * * *", every_s: null, offset_s: 0, time_zone: "Europe/Paris", catchup_window_s: 600,
  mode: "live", enabled: true, generation: 2, synced_generation: 2, misses: 0, missed_while_created: 0, misses_read_at: null,
  accounting_complete: true, uncounted_intervals: [], sync_error: null, sync_error_at: null, never_unpaused: false,
  created_at: "2026-10-11T08:00:00Z", updated_at: "2026-10-11T08:00:00Z",
};  // prettier-ignore

export const ENDPOINT: Endpoint = {
  id: "e1", name: "Mist prod", enabled: true, auth: "bearer", signature_header: null, timestamp_header: null, tolerance_s: 300,
  allowlist: [], body_limit: 1_048_576, id_source: "none", id_pointer: null, id_header: null, events_pointer: null,
  path: "/hooks/e1", pending_events: 0, pending_bytes: 0, retained_events: 0, retained_bytes: 0, created_at: "2026-10-11T08:00:00Z",
  trigger: "mist.webhook",
};  // prettier-ignore

export const BINDING: WorkflowBinding = {
  id: "b1", endpoint_id: "e1", workflow_id: "w1", enabled: true, filter: [{ pointer: "/topic", value: "device-events" }],
  endpoint: { id: "e1", name: "Mist prod", enabled: true, auth: "bearer", path: "/hooks/e1", trigger: "mist.webhook" },
};  // prettier-ignore
