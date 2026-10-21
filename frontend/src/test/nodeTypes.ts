// SPDX-License-Identifier: Apache-2.0
// Node types for tests, as GET /api/v1/node-types serves them: the flow plugin's config schemas as its catalog prints
// them (main 16406885), and a made-up service's step that takes a connection, live options and a secret (D24: never
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
        port: { pattern: "^[a-z][a-z0-9_]{0,30}$", title: "Port name", type: "string", "x-dewpoint-literal": true },
        when: { title: "Condition", type: "boolean", "x-widget": "cel" },
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
    concurrency: { default: 1, maximum: 10, minimum: 1, title: "Items at a time, at most", type: "integer", "x-dewpoint-literal": true },
    item_cap: { default: 10000, maximum: 10000, minimum: 1, title: "Items, at most", type: "integer", "x-dewpoint-literal": true },
    on_item_error: { default: "stop", enum: ["stop", "continue"], title: "When an item fails", type: "string", "x-dewpoint-literal": true },
    collect: { default: null, title: "Output for each item" },
  },
  required: ["items"], title: "LoopConfig", type: "object",
});  // prettier-ignore

export const FILTER = flow("filter", "Filter", ["out"], {
  additionalProperties: false,
  properties: {
    items: { items: {}, title: "Items", type: "array" },
    predicate: { title: "Keep an item when", type: "boolean", "x-dewpoint-kinds": ["cel"], "x-widget": "cel" },
  },
  required: ["items", "predicate"], title: "FilterConfig", type: "object",
});  // prettier-ignore

export const DELAY = flow("delay", "Delay", ["out"], {
  additionalProperties: false,
  properties: { duration_s: { maximum: 2592000, minimum: 0, title: "Duration, in seconds", type: "integer" } },
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
    workflow_id: { format: "uuid", title: "Workflow", type: "string", "x-dewpoint-literal": true },
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

/** A made-up plugin's steps in groups (4f-2: `x-group` at the config's root), as Mist's are by resource. */
const inGroup = (ref: string, title: string, group: string, more: Partial<NodeType> = {}) =>
  typeWith(
    { type: "object", additionalProperties: false, properties: {}, "x-group": { plugin: "Acme", title: group } },
    { ref, type: ref.split("@")[0], title, credentials: ["acme"], side_effect: "idempotent", ...more },
  );
export const GROUPED = [
  inGroup("acme.org_wlans.list@1", "List org WLANs", "Org WLANs", { side_effect: "none" }),
  inGroup("acme.org_wlans.create@1", "Create org WLAN", "Org WLANs", { side_effect: "ambiguous" }),
  inGroup("acme.org_wlans.update@1", "Update org WLAN", "Org WLANs"),
  inGroup("acme.org_wlans.delete@1", "Delete org WLAN", "Org WLANs"),
  inGroup("acme.site_wlans.list@1", "List site WLANs", "Site WLANs", { side_effect: "none" }),
  inGroup("acme.site_settings.update@1", "Update site settings", "Site settings"),
];

const MESSAGE_DEFS = {
  MessageField: {
    type: "object", additionalProperties: false, title: "MessageField", required: ["label", "value"],
    properties: { label: { type: "string", title: "Label", minLength: 1, maxLength: 200 }, value: { type: "string", title: "Value", maxLength: 10_000 } },
  },
  Link: {
    type: "object", additionalProperties: false, title: "Link", required: ["label", "url"],
    properties: { label: { type: "string", title: "Label", minLength: 1, maxLength: 200 }, url: { type: "string", title: "Url", maxLength: 2000 } },
  },
  Severity: { type: "string", title: "Severity", enum: ["info", "success", "warning", "critical"] },
};  // prettier-ignore

/** A step that sends a message (4f-1): its config the SDK's message as `class SendConfig(Message)` makes it, the
 * composer's hint at its root, with a connection and `more`. Made up (D24), named as the target to preview. */
export const messageStep = (type: string, more: Record<string, unknown> = {}, required: string[] = []): NodeType =>
  typeWith({
    type: "object", additionalProperties: false, "x-widget": "message", $defs: MESSAGE_DEFS, required: ["text", "connection", ...required],
    properties: {
      title: { anyOf: [{ type: "string", maxLength: 1000 }, { type: "null" }], default: null, title: "Title" },
      text: { type: "string", title: "Text", minLength: 1, maxLength: 40_000 },
      fields: { type: "array", title: "Fields", maxItems: 25, items: { $ref: "#/$defs/MessageField" } },
      links: { type: "array", title: "Links", maxItems: 10, items: { $ref: "#/$defs/Link" } },
      severity: { $ref: "#/$defs/Severity", default: "info" },
      connection: { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": type.split(".")[0] },
      ...more,
    },
  }, { ref: `${type}@1`, type, title: "Send a message", credentials: [type.split(".")[0]!] });  // prettier-ignore

/** A made-up service's update and create steps (4f-2b), shaped as Mist's are: the body a `$defs` component, settings
 * titled on their own entries, a read-only one, objects, a map and a list of objects, a union, sensitive parts; an
 * update's `mode` and `clear` (D24: never Mist's own). */
const SETTING_DEFS = {
  thing: {
    type: "object",
    properties: {
      id: { $ref: "#/$defs/id", title: "ID", description: "Unique ID of the object" },
      name: { type: "string", title: "Name", description: "The thing's name" },
      enabled: { type: "boolean", title: "Enabled", description: "Whether the thing runs" },
      rogue: { $ref: "#/$defs/rogue", title: "Rogue", description: "AP threat detection settings for the site" },
      auto_upgrade: { $ref: "#/$defs/auto_upgrade", title: "Auto upgrade", description: "Automatic upgrade settings" },
      port_usages: { type: "object", title: "Port usages", description: "Port profiles by name", additionalProperties: { $ref: "#/$defs/port_usage" } },
      networks: { type: "array", title: "Networks", description: "The networks served", items: { $ref: "#/$defs/network" } },
      tags: { type: "array", title: "Tags", description: "Free tags", items: { type: "string" } },
      vlan_id: { anyOf: [{ type: "integer", minimum: 1, maximum: 4094 }, { type: "string" }], title: "VLAN ID", description: "A number or a variable" },
      api_secret: { type: "string", title: "API secret", description: "The service's secret", "x-sensitive": true },
      radius: { $ref: "#/$defs/radius", title: "RADIUS", description: "The RADIUS server" },
    },
  },
  id: { type: "string", format: "uuid", readOnly: true },
  rogue: {
    type: "object",
    description: "Rogue AP detection settings for a site",
    properties: {
      enabled: { type: "boolean", title: "Enabled", description: "Whether rogue detection is enabled" },
      min_rogue_rssi: { type: "integer", minimum: -85, title: "Min rogue RSSI", description: "Minimum RSSI for an AP to be considered rogue" },
      whitelisted_ssids: { type: "array", items: { type: "string" }, title: "Whitelisted SSIDs", description: "SSID names excluded from rogue detection" },
    },
  },
  auto_upgrade: {
    type: "object",
    properties: {
      enabled: { type: "boolean", title: "Enabled", description: "Whether auto upgrade should happen" },
      version: { type: "string", enum: ["beta", "custom", "stable"], title: "Version", description: "Desired version" },
      time_of_day: { type: "string", title: "Time of day", description: "HH:MM, 24-hour" },
      custom: { type: "object", title: "Custom versions", description: "A version per model", properties: { ap41: { type: "string", title: "AP41", description: "The AP41's version" } } },
      schedules: { type: "array", title: "Schedules", description: "When to upgrade", items: { type: "object", properties: { day: { type: "string", title: "Day", description: "The day" } } } },
      profiles: { type: "object", title: "Profiles", description: "A profile per radio", additionalProperties: { type: "object", properties: { channel: { type: "string", title: "Channel", description: "Its channel" } } } },
    },
  },
  port_usage: {
    type: "object",
    properties: {
      mode: { type: "string", enum: ["access", "trunk"], title: "Mode", description: "How the port is used" },
      port_vlan: { type: "integer", title: "Port VLAN", description: "The port's native VLAN" },
    },
  },
  network: {
    type: "object",
    properties: {
      id: { $ref: "#/$defs/id", title: "ID", description: "Set by the service" },
      name: { type: "string", title: "Name", description: "The network's name" },
      subnet: { type: "string", title: "Subnet", description: "The network's subnet" },
    },
  },
  radius: {
    type: "object",
    properties: {
      host: { type: "string", title: "Host", description: "The server's host" },
      secret: { type: "string", title: "Secret", description: "The shared secret", "x-sensitive": true },
    },
  },
};
const CONNECTION = { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": "acme" };
const THING_ID = { title: "Thing ID", type: "string", format: "uuid", "x-dewpoint-options": true };
const NAMES = ["api_secret", "auto_upgrade", "enabled", "id", "name", "networks", "port_usages", "radius", "rogue", "tags", "vlan_id"];

/** An update: its body, merge or replace, and the settings to clear (`x-widget: "update"`). */
export const UPDATE = typeWith({
  type: "object", additionalProperties: false, required: ["connection", "thing_id"], "x-widget": "update",
  "x-group": { plugin: "Acme", title: "Things" },
  properties: {
    connection: CONNECTION,
    thing_id: THING_ID,
    body: { title: "Body", $ref: "#/$defs/thing" },
    mode: { enum: ["merge", "replace"], default: "merge", title: "Mode" },
    clear: { type: "array", title: "Fields to clear", uniqueItems: true, items: { enum: NAMES } },
  },
  $defs: SETTING_DEFS,
}, { ref: "acme.things.update@1", type: "acme.things.update", title: "Update thing", options: ["thing_id"], credentials: ["acme"], side_effect: "idempotent" });  // prettier-ignore

/** A create: its body, its name required (`x-widget: "create"`). */
export const CREATE = typeWith({
  type: "object", additionalProperties: false, required: ["connection", "body"], "x-widget": "create",
  "x-group": { plugin: "Acme", title: "Things" },
  properties: { connection: CONNECTION, body: { title: "Body", $ref: "#/$defs/new_thing" } },
  $defs: { ...SETTING_DEFS, new_thing: { ...SETTING_DEFS.thing, required: ["name"] } },
}, { ref: "acme.things.create@1", type: "acme.things.create", title: "Create thing", credentials: ["acme"], side_effect: "ambiguous" });  // prettier-ignore

const KIND_DEFS = {
  device: { description: "A device: a camera or a sensor", anyOf: [{ $ref: "#/$defs/camera", title: "Camera" }, { $ref: "#/$defs/sensor", title: "Sensor" }], title: "Device" },
  camera: {
    type: "object",
    properties: {
      type: { $ref: "#/$defs/kind_camera", title: "Type" },
      name: { type: "string", title: "Name", description: "The device's name" },
      notes: { type: "string", title: "Notes", description: "Any notes" },
      zoom: { type: "integer", title: "Zoom", description: "The camera's zoom" },
    },
  },
  sensor: {
    type: "object",
    properties: {
      type: { $ref: "#/$defs/kind_sensor", title: "Type" },
      name: { type: "string", title: "Name", description: "The device's name" },
      notes: { type: "string", title: "Notes", description: "Any notes" },
      range: { type: "integer", title: "Range", description: "The sensor's range" },
    },
  },
};

/** A device update whose body is a union of kinds, each allowing one `type`, read only (as Mist's devices). */
export const DEVICE_UPDATE = typeWith({
  type: "object", additionalProperties: false, required: ["connection"], "x-widget": "update",
  properties: {
    connection: CONNECTION,
    body: { title: "Body", $ref: "#/$defs/device" },
    mode: { enum: ["merge", "replace"], default: "merge", title: "Mode" },
    clear: { type: "array", title: "Fields to clear", uniqueItems: true, items: { enum: ["name", "notes", "range", "type", "zoom"] } },
  },
  $defs: { ...KIND_DEFS, kind_camera: { enum: ["camera"], type: "string", readOnly: true }, kind_sensor: { enum: ["sensor"], type: "string", readOnly: true } },
}, { ref: "acme.devices.update@1", type: "acme.devices.update", title: "Update device", credentials: ["acme"], side_effect: "idempotent" });  // prettier-ignore

/** A device create: the kind's `type` required (as Mist's device profiles). */
export const DEVICE_CREATE = typeWith({
  type: "object", additionalProperties: false, required: ["connection", "body"], "x-widget": "create",
  properties: { connection: CONNECTION, body: { title: "Body", $ref: "#/$defs/device" } },
  $defs: {
    ...KIND_DEFS,
    camera: { ...KIND_DEFS.camera, required: ["type"] },
    sensor: { ...KIND_DEFS.sensor, required: ["type", "name"] },
    kind_camera: { enum: ["camera"], type: "string" },
    kind_sensor: { enum: ["sensor"], type: "string", readOnly: true },
  },
}, { ref: "acme.devices.create@1", type: "acme.devices.create", title: "Create device", credentials: ["acme"], side_effect: "ambiguous" });  // prettier-ignore
