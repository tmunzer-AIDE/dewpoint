// SPDX-License-Identifier: Apache-2.0
// Node types for tests, as GET /api/v1/node-types serves them: the flow plugin's config schemas as its catalog prints
// them (main 0838e4f), and a made-up service's step that takes a connection, live options and a secret (D24: never
// Mist's own).
import type { NodeType } from "../lib/workflows";

const RETRY = { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] };

export const typeWith = (config_schema: Record<string, unknown>, more: Partial<NodeType> = {}): NodeType => ({
  ref: "test.step@1", type: "test.step", version: 1, kind: "action", state: "active", title: "Test step",
  description: "", icon: null, ports: ["out"], dynamic_ports: null, options: [], config_schema, output_schema: {},
  side_effect: "none", credentials: [], capabilities: [], retry: RETRY, timeout_s: 60, ...more,
});  // prettier-ignore

const flow = (name: string, title: string, ports: string[], schema: Record<string, unknown>, more: Partial<NodeType> = {}) =>
  typeWith(schema, { ref: `flow.${name}@1`, type: `flow.${name}`, kind: "control", title, ports, ...more });

export const IF = flow("if", "If", ["true", "false"], {
  additionalProperties: false, properties: { condition: { title: "Condition", type: "boolean", "x-widget": "cel" } },
  required: ["condition"], title: "IfConfig", type: "object",
});  // prettier-ignore

export const SWITCH = flow("switch", "Switch", ["default"], {
  $defs: {
    SwitchCase: {
      additionalProperties: false,
      properties: {
        port: { pattern: "^[a-z][a-z0-9_]{0,30}$", title: "Port", type: "string", "x-dewpoint-literal": true },
        when: { title: "When", type: "boolean", "x-widget": "cel" },
      },
      required: ["port", "when"], title: "SwitchCase", type: "object",
    },
  },
  additionalProperties: false,
  properties: { cases: { items: { $ref: "#/$defs/SwitchCase" }, maxItems: 20, minItems: 1, title: "Cases", type: "array" } },
  required: ["cases"], title: "SwitchConfig", type: "object",
}, { dynamic_ports: "cases" });  // prettier-ignore

export const LOOP = flow("loop", "Loop", ["body", "done"], {
  additionalProperties: false,
  properties: {
    items: { items: {}, title: "Items", type: "array" },
    concurrency: { default: 1, maximum: 10, minimum: 1, title: "Concurrency", type: "integer", "x-dewpoint-literal": true },
    item_cap: { default: 10000, maximum: 10000, minimum: 1, title: "Item Cap", type: "integer", "x-dewpoint-literal": true },
    on_item_error: { default: "stop", enum: ["stop", "continue"], title: "On Item Error", type: "string", "x-dewpoint-literal": true },
    collect: { default: null, title: "Collect" },
  },
  required: ["items"], title: "LoopConfig", type: "object",
});  // prettier-ignore

export const FILTER = flow("filter", "Filter", ["out"], {
  additionalProperties: false,
  properties: {
    items: { items: {}, title: "Items", type: "array" },
    predicate: { title: "Predicate", type: "boolean", "x-dewpoint-kinds": ["cel"], "x-widget": "cel" },
  },
  required: ["items", "predicate"], title: "FilterConfig", type: "object",
});  // prettier-ignore

export const DELAY = flow("delay", "Delay", ["out"], {
  additionalProperties: false,
  properties: { duration_s: { maximum: 2592000, minimum: 0, title: "Duration S", type: "integer" } },
  required: ["duration_s"], title: "DelayConfig", type: "object",
});  // prettier-ignore

export const TRANSFORM = flow("transform", "Transform", ["out"], {
  additionalProperties: false,
  properties: { fields: { additionalProperties: true, maxProperties: 100, minProperties: 1, title: "Fields", type: "object" } },
  required: ["fields"], title: "TransformConfig", type: "object",
});  // prettier-ignore

export const RUN_WORKFLOW = flow("run_workflow", "Run workflow", ["out"], {
  additionalProperties: false,
  properties: {
    workflow_id: { format: "uuid", title: "Workflow Id", type: "string", "x-dewpoint-literal": true },
    input: { additionalProperties: true, title: "Input", type: "object" },
  },
  required: ["workflow_id"], title: "RunWorkflowConfig", type: "object",
});  // prettier-ignore

/** A made-up service's step: a connection, a site among live choices, a secret, and the other shapes a schema takes. */
export const REMOTE = typeWith({
  type: "object", additionalProperties: false, required: ["connection", "site_id"],
  properties: {
    connection: { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": "acme" },
    site_id: { type: "string", title: "Site", "x-dewpoint-options": true },
    token: { type: "string", title: "Token", "x-sensitive": true },
    query: {
      type: "object", title: "Query", additionalProperties: false,
      properties: { limit: { type: "integer", title: "Limit", default: 100, description: "How many to list." } },
    },
    mode: { type: "string", enum: ["fast", "safe"], title: "Mode" },
    when: { type: "string", format: "date-time", title: "When" },
    tags: { type: "array", title: "Tags", items: { type: "string" } },
    note: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Note" },
  },
}, { ref: "acme.sites@1", type: "acme.sites", title: "Sites", options: ["site_id"], credentials: ["acme"] });  // prettier-ignore
