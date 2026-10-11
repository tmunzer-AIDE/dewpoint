// SPDX-License-Identifier: Apache-2.0
// What starts a workflow (4c-3b): its schedules, its webhook bindings and their endpoints, the trigger types the
// plugins declare, the published version's start form; and the words the Triggers panel, the list and Settings share.
// Types from the generated schema (B1, 4c-3a's named answers), never written by hand. The API decides every write.
import { queryOptions } from "@tanstack/react-query";
import { ApiError, client, ok, type Schemas } from "./client";
import { timingTitle, whenOf } from "./timing";

export type Schedule = Schemas["ScheduleOut"];
export type ScheduleIn = Schemas["ScheduleIn"];
export type SchedulePatch = Schemas["SchedulePatch"];
export type Endpoint = Schemas["EndpointOut"];
export type EndpointIn = Schemas["EndpointIn"];
export type EndpointPatch = Schemas["EndpointPatch"];
export type EndpointBinding = Schemas["WebhookBindingOut"];
export type WorkflowBinding = Schemas["WorkflowBindingOut"];
export type FilterClause = Schemas["FilterClauseOut"];
export type TriggerType = Schemas["TriggerTypeOut"];
export type StartForm = Schemas["StartFormOut"];
export type StartField = Schemas["StartFieldOut"];
export type TriggerCounts = Schemas["TriggersOut"];
export type Attention = Schemas["WorkflowOut"]["needs_attention"][number];

const tenant = (tenantId: string) => ({ params: { path: { tenant_id: tenantId } } });
const workflow = (tenantId: string, workflowId: string) => ({ params: { path: { tenant_id: tenantId, workflow_id: workflowId } } });

export const schedulesQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["schedules", tenantId, workflowId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/schedules", workflow(tenantId, workflowId))),
  });

/** A workflow's webhook bindings, each with its endpoint (B13). */
export const workflowBindingsQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["workflow-bindings", tenantId, workflowId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/webhook-bindings", workflow(tenantId, workflowId))),
  });

export const endpointsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["endpoints", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/webhook-endpoints", tenant(tenantId))),
  });

/** An endpoint's bindings, the workflows it starts. */
export const endpointBindingsQuery = (tenantId: string, endpointId: string) =>
  queryOptions({
    queryKey: ["endpoint-bindings", tenantId, endpointId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", {
        params: { path: { tenant_id: tenantId, endpoint_id: endpointId } },
      })),
  });

/** The trigger types synced plugins declare: Mist's webhook, its topics and their shapes. */
export const triggerTypesQuery = queryOptions({
  queryKey: ["trigger-types"],
  queryFn: () => ok(client.GET("/api/v1/trigger-types")),
  staleTime: 5 * 60_000,
});

/** The published version's start form; null while nothing is published (`409 not_active`). */
export const startFormQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["start-form", tenantId, workflowId],
    queryFn: async () => {
      try {
        return await ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/start-form", workflow(tenantId, workflowId)));
      } catch (e) {
        if (e instanceof ApiError && e.code === "not_active") return null;
        throw e;
      }
    },
  });

/** A version's graph, read once: a published version never changes. */
export const versionQuery = (tenantId: string, workflowId: string, versionId: string) =>
  queryOptions({
    queryKey: ["version", tenantId, workflowId, versionId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}", {
        params: { path: { tenant_id: tenantId, workflow_id: workflowId, version_id: versionId } },
      })),
    staleTime: Infinity,
  });

export const createSchedule = (tenantId: string, workflowId: string, body: ScheduleIn) =>
  ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/schedules", { ...workflow(tenantId, workflowId), body }));
export const updateSchedule = (tenantId: string, scheduleId: string, body: SchedulePatch) =>
  ok(client.PATCH("/api/v1/t/{tenant_id}/schedules/{schedule_id}", { params: { path: { tenant_id: tenantId, schedule_id: scheduleId } }, body }));
export const deleteSchedule = (tenantId: string, scheduleId: string) =>
  ok(client.DELETE("/api/v1/t/{tenant_id}/schedules/{schedule_id}", { params: { path: { tenant_id: tenantId, schedule_id: scheduleId } } }));

export const createBinding = (tenantId: string, endpointId: string, body: Schemas["BindingIn"]) =>
  ok(client.POST("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", {
    params: { path: { tenant_id: tenantId, endpoint_id: endpointId } },
    body,
  }));
export const updateBinding = (tenantId: string, bindingId: string, body: Schemas["BindingPatch"]) =>
  ok(client.PATCH("/api/v1/t/{tenant_id}/webhook-bindings/{binding_id}", { params: { path: { tenant_id: tenantId, binding_id: bindingId } }, body }));
export const deleteBinding = (tenantId: string, bindingId: string) =>
  ok(client.DELETE("/api/v1/t/{tenant_id}/webhook-bindings/{binding_id}", { params: { path: { tenant_id: tenantId, binding_id: bindingId } } }));

export const createEndpoint = (tenantId: string, body: EndpointIn) =>
  ok(client.POST("/api/v1/t/{tenant_id}/webhook-endpoints", { ...tenant(tenantId), body }));
export const updateEndpoint = (tenantId: string, endpointId: string, body: EndpointPatch) =>
  ok(client.PATCH("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}", { params: { path: { tenant_id: tenantId, endpoint_id: endpointId } }, body }));
export const rotateSecret = (tenantId: string, endpointId: string) =>
  ok(client.POST("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/secret", { params: { path: { tenant_id: tenantId, endpoint_id: endpointId } } }));

const plural = (n: number, one: string, many: string) => (n === 1 ? one : `${n} ${many}`);

/** What starts a run, on the start card: by hand always (once published), then what else does. */
export function startSummary(t: { csv: boolean; schedules: number; webhooks: number }): string {
  const parts = [t.csv ? "By hand, with a CSV file" : "By hand"];
  if (t.schedules > 0) parts.push(t.schedules === 1 ? "1 schedule" : `${t.schedules} schedules`);
  if (t.webhooks > 0) parts.push(t.webhooks === 1 ? "1 webhook" : `${t.webhooks} webhooks`);
  return parts.join(" · ");
}

/** The start card's name: its visible words first (WCAG 2.5.3), then what it opens. */
export const startLabel = (summary: string) => `Start: ${summary.charAt(0).toLowerCase()}${summary.slice(1).replaceAll(" · ", ", ")}. Open its triggers`;

/** The list's Trigger column (ruling 68): what starts a workflow besides a person, by hand being always possible once
 * published. A workflow that takes a CSV file runs only by hand, with a file. */
export function triggerColumn(t: TriggerCounts): string {
  if (t.csv) return "CSV file";
  const [s, w] = [t.schedules, t.webhook_bindings];
  if (s > 0 && w > 0) return `${plural(s, "1 schedule", "schedules")} · ${plural(w, "1 webhook", "webhooks")}`;
  if (s > 0) return plural(s, "Schedule", "schedules");
  if (w > 0) return plural(w, "Webhook", "webhooks");
  return "By hand";
}

const ATTENTION: Record<Attention, string> = {
  last_run_failed: "its last run failed",
  not_executable: "its active version can't run",
  schedule_sync_failed: "a schedule couldn't be synced",
};

/** Why a workflow needs attention, in a sentence: null when it doesn't. */
export function attentionWords(reasons: readonly Attention[]): string | null {
  const said = reasons.map((r) => ATTENTION[r]);
  if (said.length === 0) return null;
  const joined = said.length === 1 ? said[0]! : `${said.slice(0, -1).join(", ")} and ${said.at(-1)!}`;
  return `Needs attention: ${joined}.`;
}

const TIME = (zone?: string) => new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: zone });

/** A schedule's second line: its zone where one applies (a cron's), its mode, whether it's off, a custom cron, and
 * "synced" once the scheduler holds its latest change. */
export function scheduleMeta(s: Schedule): string {
  const custom = s.cron !== null && whenOf(s).preset === "custom";
  return [
    s.cron !== null ? s.time_zone : null,
    s.mode === "simulate" ? "simulated: nothing is sent" : "live",
    s.enabled ? null : "off",
    custom ? "custom" : null,
    s.generation === s.synced_generation && s.sync_error === null ? "synced" : null,
  ].filter((p) => p !== null).join(" · ");
}

/** What a schedule's sync proves, when it isn't synced (the D8 reviews; 4c-3a ruling 6). A failed sync pauses nothing:
 * the previous time may still fire. One never synced may already fire (the unpause can land before its read-back
 * fails), unless nothing ever unpaused it: then it isn't running yet. */
export function scheduleNote(s: Schedule): string | null {
  const first = s.synced_generation === 0;
  if (s.sync_error !== null) {
    if (first && s.never_unpaused)
      return "Sync failed: the scheduler refused it, so it isn't running yet. Dewpoint tries again every minute, and the workflow shows as needing attention.";
    if (first)
      return "Sync failed: the scheduler refused it, and its sync was never confirmed, so it may already fire. Dewpoint tries again every minute, and the workflow shows as needing attention; turning it off stops new runs at once.";
    return "Sync failed: the scheduler refused this change. Its previous time may still fire, with the input and mode saved now. Dewpoint tries again every minute; turning it off stops new runs at once.";
  }
  if (s.generation === s.synced_generation) return null;
  if (first) return s.never_unpaused ? "Saved; not running yet: the scheduler takes it on its own, usually within seconds." : "Saved; sync not yet confirmed: it may already fire.";
  return "Saved; sync not yet confirmed: until it is, the previous time or the new one may fire.";
}

/** The firings a schedule missed, as counted, and whether some may be missed still. */
export function missesNote(s: Schedule, zone?: string): string | null {
  if (s.misses === 0) return s.accounting_complete ? null : "Some firings may be missed, not yet counted.";
  const at = s.misses_read_at ? `, counted at ${TIME(zone).format(new Date(s.misses_read_at))}` : "";
  const missed = `${plural(s.misses, "1 firing", "firings")} missed${at}.`;
  return s.accounting_complete ? missed : `${missed} Some may be missed still, not yet counted.`;
}

export const scheduleTitle = (s: Schedule) => timingTitle(s);

/** A name's possessive, as the boards write it: "device-events' shape", "alarm's shape". */
export const possessive = (name: string) => `${name}${name.endsWith("s") ? "'" : "'s"}`;

/** A trigger type's sender, as a person says it: "Mist" for "Mist webhook". */
export const senderName = (t: TriggerType) => t.label.replace(/ webhook$/i, "");

/** A filter value as its row says it: the form's text for it, which reads as the value and shows its spaces and quotes. */
export const valueWords = (v: FilterClause["value"]): string => valueText(v);

/** A filter in words: "/type is incident and /priority is 1"; none matches every event. */
export const filterWords = (filter: FilterClause[]) =>
  filter.length === 0 ? "every event" : filter.map((c) => `${c.pointer} is ${valueWords(c.value)}`).join(" and ");

/** The topic a filter picks for a trigger type: one clause on its topic pointer, naming one of its topics. */
export function topicOf(filter: FilterClause[], type: TriggerType | undefined): string | null {
  const [only] = filter;
  if (!type || filter.length !== 1 || only?.pointer !== type.topic_pointer || typeof only.value !== "string") return null;
  return Object.hasOwn(type.topics, only.value) ? only.value : null;
}

/** What a binding's endpoint sends and when the binding runs, in its row: "Mist · topic device-events", or "Another
 * sender · /type is incident". An endpoint made for a trigger no plugin declares any more says so. */
export function bindingLine(b: { endpoint: { trigger: string | null }; filter: FilterClause[] }, types: TriggerType[] | undefined): string {
  const key = b.endpoint.trigger;
  // What senders there are isn't known yet, or couldn't be read: the sender by its key, never "unknown" (the final review).
  if (key !== null && types === undefined) return `${key} · ${filterWords(b.filter)}`;
  const type = key === null ? undefined : types?.find((t) => t.key === key);
  if (key !== null && !type) return `An unknown sender (${key}) · ${filterWords(b.filter)}`;
  if (!type) return `Another sender · ${filterWords(b.filter)}`;
  const topic = topicOf(b.filter, type);
  return `${senderName(type)} · ${topic ? `topic ${topic}` : filterWords(b.filter)}`;
}

const INT = /^-?(0|[1-9]\d*)$/;

/** A filter value as typed (the binding form): a whole number, true, false or null as written; text in quotes read as
 * JSON text, its spaces, quotes and escapes kept; anything else as text, without the spaces around it. Never a float:
 * the API refuses one. */
export function parseValue(text: string): { value: FilterClause["value"] } | { problem: string } {
  const t = text.trim();
  if (INT.test(t)) {
    const n = Number(t);
    return Number.isSafeInteger(n) ? { value: n } : { problem: "A whole number this large can't be kept exactly: put it in quotes to match it as text." };
  }
  if (t === "true" || t === "false") return { value: t === "true" };
  if (t === "null") return { value: null };
  let inner = t;
  if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
    try {
      inner = JSON.parse(t) as string;
    } catch {
      return { problem: 'Text in quotes is read as JSON text: write \\" for a quote inside it.' };
    }
  }
  return inner.length > 1024 ? { problem: "At most 1,024 characters." } : { value: inner };
}

/** A filter value as the form shows it, so that reading it again gives it back exactly (the review of revision 1): text
 * as itself when that reads back as it, else as JSON text in quotes (" HQ ", "42", "" and a quote at each end), and so
 * is text with a line break, which a one-line field would drop (the final review). */
export function valueText(v: FilterClause["value"]): string {
  if (typeof v !== "string") return v === null ? "null" : String(v);
  const read = parseValue(v);
  return v !== "" && !/[\r\n]/.test(v) && "value" in read && read.value === v ? v : JSON.stringify(v);
}
