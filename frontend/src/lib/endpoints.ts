// SPDX-License-Identifier: Apache-2.0
// Webhook endpoints in words, and the new endpoint's form as the API takes it (4c-3b; the Endpoints, EndpointNew and
// EndpointOther boards; 4c-3a ruling 1). An endpoint made for a trigger takes that trigger's settings; another
// sender's says how it proves itself, where its events are and where their ids are, all fixed once it's made. The
// API checks every field and names those it refuses (`endpoint_invalid`); the words for each are here.
import type { Endpoint, EndpointIn, EndpointPatch, TriggerType } from "./triggers";
import { senderName } from "./triggers";

export const BODY_LIMITS = [
  { value: 262_144, label: "256 KB" },
  { value: 1_048_576, label: "1 MB" },
  { value: 5_242_880, label: "5 MB" },
] as const;
export const TOLERANCES = [
  { value: 60, label: "1 minute" },
  { value: 300, label: "5 minutes" },
  { value: 900, label: "15 minutes" },
] as const;
export const SIGNATURE_HEADER = "x-dewpoint-signature";
export const TIMESTAMP_HEADER = "x-dewpoint-timestamp";

/** What the new endpoint's form holds: a trigger's key, or another sender's own settings. */
export interface EndpointForm {
  name: string;
  trigger: string | null; // a trigger type's key, or null for another sender
  auth: "bearer" | "hmac";
  signature: string;
  timestamp: string;
  tolerance: number;
  events: "body" | "list" | "at"; // the body is one event, a list of them, or holds a list at `eventsAt`
  eventsAt: string;
  ids: "none" | "pointer" | "header";
  idPointer: string;
  idHeader: string;
  allowlist: string; // one network a line
  bodyLimit: number;
}

export const blankForm = (trigger: string | null): EndpointForm => ({
  name: "", trigger, auth: "bearer", signature: SIGNATURE_HEADER, timestamp: TIMESTAMP_HEADER, tolerance: 300, events: "body",
  eventsAt: "/items", ids: "none", idPointer: "/id", idHeader: "x-request-id", allowlist: "", bodyLimit: 1_048_576,
});  // prettier-ignore

/** An allowlist as typed, one network a line, blank lines dropped. */
export const allowlistOf = (text: string): string[] => text.split("\n").map((l) => l.trim()).filter((l) => l !== "");

/** The form as the API takes it: a trigger's endpoint names only its trigger, its name and its limits. */
export function endpointBody(f: EndpointForm): EndpointIn {
  const common = { name: f.name.trim(), allowlist: allowlistOf(f.allowlist), body_limit: f.bodyLimit };
  if (f.trigger !== null) return { ...common, trigger: f.trigger };
  return {
    ...common,
    auth: f.auth,
    ...(f.auth === "hmac" ? { signature_header: f.signature.trim(), timestamp_header: f.timestamp.trim(), tolerance_s: f.tolerance } : {}),
    events_pointer: f.events === "body" ? null : f.events === "list" ? "" : f.eventsAt.trim(),
    id_source: f.ids,
    ...(f.ids === "pointer" ? { id_pointer: f.idPointer.trim() } : f.ids === "header" ? { id_header: f.idHeader.trim().toLowerCase() } : {}),
  };
}

/** What an edit changes: only the fields it may (the API's UPDATABLE), and only those changed. */
export function endpointPatch(e: Endpoint, f: Pick<EndpointForm, "name" | "signature" | "timestamp" | "tolerance" | "allowlist" | "bodyLimit">): EndpointPatch {
  const out: EndpointPatch = {};
  if (f.name.trim() !== e.name) out.name = f.name.trim();
  if (e.auth === "hmac" && f.signature.trim() !== e.signature_header) out.signature_header = f.signature.trim();
  if (e.auth === "hmac" && f.timestamp.trim() !== e.timestamp_header) out.timestamp_header = f.timestamp.trim();
  if (e.auth === "hmac" && f.tolerance !== e.tolerance_s) out.tolerance_s = f.tolerance;
  const allowlist = allowlistOf(f.allowlist);
  if (allowlist.join("\n") !== e.allowlist.join("\n")) out.allowlist = allowlist;
  if (f.bodyLimit !== e.body_limit) out.body_limit = f.bodyLimit;
  return out;
}

/** The API's refusals of an endpoint's fields (`endpoint_invalid`'s `fields`), in words, by the field they show at. */
export const FIELD_WORDS: Record<string, string> = {
  trigger: "No plugin declares this sender any more.",
  events_pointer: "A pointer into the body starts with /, like /items, at most 256 characters.",
  id_pointer: "A pointer starts with /, like /id, at most 256 characters.",
  id_header: "A header's name: lowercase letters, digits and -, not one a proxy sets, like authorization or host.",
  signature_header: "A header's name: lowercase letters, digits and -, not one a proxy sets.",
  timestamp_header: "A header's name: lowercase letters, digits and -, not one a proxy sets.",
  allowlist: "One network a line, like 203.0.113.0/24, with no host bits past its prefix; up to 32.",
  auth: "This sender decides how it proves itself.",
};

export const proofWords = (auth: string) => (auth === "hmac" ? "An HMAC signature" : "A token");

/** Where an endpoint's events are, in words. */
export function eventsWords(pointer: string | null): string {
  if (pointer === null) return "The body is one event";
  if (pointer === "") return "The body is a list of events";
  return `The list at ${pointer}`;
}

/** Where an endpoint's events' ids are, in words. */
export function idsWords(e: Pick<Endpoint, "id_source" | "id_pointer" | "id_header">): string {
  if (e.id_source === "pointer") return `At ${e.id_pointer ?? ""} in each event`;
  if (e.id_source === "header") return `In the ${e.id_header ?? ""} header`;
  return "None";
}

/** Who sends to an endpoint: its trigger's sender, another sender, or one no plugin declares any more. */
export function senderWords(trigger: string | null, types: TriggerType[] | undefined): string {
  if (trigger === null) return "Another sender";
  if (types === undefined) return trigger; // what senders there are isn't known yet, or couldn't be read: never "unknown"
  const type = types.find((t) => t.key === trigger);
  return type ? senderName(type) : `An unknown sender (${trigger})`;
}

/** What's fixed once another sender's endpoint is made, as the form says it before (the EndpointOther board). */
export function fixedWords(f: EndpointForm): string {
  const events = f.events === "body" ? "each delivery one event" : f.events === "list" ? "events in a list, the body" : f.eventsAt.trim().startsWith("/") ? `events in the list at ${f.eventsAt.trim()}` : "events in a list: its pointer needs fixing first";
  const ids =
    f.ids === "none" ? "no ids"
    : f.ids === "pointer" ? (f.idPointer.trim().startsWith("/") ? `each event's id at ${f.idPointer.trim()}` : "each event's id: its pointer needs fixing first")
    : f.idHeader.trim() === "" ? "each event's id: its header needs naming first" : `each event's id in the ${f.idHeader.trim().toLowerCase()} header`;  // prettier-ignore
  return `Fixed once made: ${proofWords(f.auth).replace(/^A/, "a")}; ${events}; ${ids}.`;
}

/** How a sender uses an endpoint's secret, beside the secret shown once. */
export function secretWords(e: Pick<Endpoint, "auth" | "signature_header" | "timestamp_header" | "tolerance_s">, sender: string): string {
  if (e.auth === "hmac") {
    const off = TOLERANCES.find((t) => t.value === e.tolerance_s)?.label ?? `${e.tolerance_s} seconds`;
    return `The sender signs the Unix time in seconds, a dot, then the raw body, with HMAC-SHA256 under this secret. It sends the hex digest in ${e.signature_header ?? SIGNATURE_HEADER} (sha256= in front is fine) and the time in ${e.timestamp_header ?? TIMESTAMP_HEADER}. A time more than ${off} off is refused.`;
  }
  return `${sender === "Another sender" ? "The sender" : `In ${sender}'s webhook, the sender`} sends it in a header: Authorization: Bearer and the token. Lost, it can't be shown again: rotate it for a new one.`;
}
