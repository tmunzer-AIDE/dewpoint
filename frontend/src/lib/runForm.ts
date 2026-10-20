// SPDX-License-Identifier: Apache-2.0
// The run form (editor 4e-2; the run form design §5): its calls, as the generated schema types them (B1); who may
// start, and what can; the key a submission is sent under; a newer version's form keeping what was typed; and what a
// refused start or a CSV file says, in words.
import { ApiError, client, ok, type Schemas } from "./client";
import { mbOf } from "./csv";
import { reasonWords } from "./runStatus";
import type { StartForm } from "./triggers";
import type { WorkflowRow } from "./workflows";

export type { StartForm };
export type StartBody = Schemas["StartIn"];
export type RerunBody = Schemas["RerunIn"];
export type RunRequest = Schemas["RequestOut"];
export type CsvUpload = Schemas["CsvUploadOut"];
export type CsvPreview = Schemas["CsvPreviewOut"];
export type CsvSaved = Schemas["CsvMappingOut"];
export type Mapping = Record<string, string>;

const workflow = (tenantId: string, workflowId: string) => ({ tenant_id: tenantId, workflow_id: workflowId });

/** Starts the workflow's published version (§5.2): its request, admitted (202), or an ApiError in the server's words. */
export const startRun = (tenantId: string, workflowId: string, body: StartBody, key: string): Promise<RunRequest> =>
  ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/runs", {
    params: { path: workflow(tenantId, workflowId), header: { "Idempotency-Key": key } }, body,
  }));  // prettier-ignore

/** Runs a run's workflow again through its own route (§5.4). */
export const rerunRun = (tenantId: string, runId: string, body: RerunBody, key: string): Promise<RunRequest> =>
  ok(client.POST("/api/v1/t/{tenant_id}/runs/{request_id}/rerun", {
    params: { path: { tenant_id: tenantId, request_id: runId }, header: { "Idempotency-Key": key } }, body,
  }));  // prettier-ignore

/** Stages a CSV file (§5.3): its bytes as they are, `text/csv`, the server reading them as they arrive and checking
 * their encoding itself (read as text here, a bad byte would be replaced, never refused). The route declares no body (it
 * reads the stream itself), so the bytes go through a serializer of their own. */
export async function uploadCsv(tenantId: string, workflowId: string, file: Blob): Promise<CsvUpload> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  return ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-uploads", {
    params: { path: workflow(tenantId, workflowId) },
    body: bytes as never,
    bodySerializer: () => bytes,
    headers: { "Content-Type": "text/csv" },
  }));  // prettier-ignore
}

/** A staged file described again under other columns (B11; §5.3). */
export const previewCsv = (tenantId: string, workflowId: string, uploadId: string, mapping: Mapping): Promise<CsvPreview> =>
  ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-uploads/{upload_id}/preview", {
    params: { path: { ...workflow(tenantId, workflowId), upload_id: uploadId } }, body: { mapping },
  }));  // prettier-ignore

/** The columns saved for the workflow's next CSV (§5.3; `trigger.manage`). */
export const saveColumns = (tenantId: string, workflowId: string, mapping: Mapping): Promise<CsvSaved> =>
  ok(client.PUT("/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-mapping", { params: { path: workflow(tenantId, workflowId) }, body: { mapping } }));

// The roles that hold run.start (operator and up) and trigger.manage (editor and up), as
// backend/src/dewpoint/core/authz/permissions.py grants them. The UI only hides what the API would refuse.
const STARTERS = new Set(["owner", "admin", "editor", "operator"]);
const TRIGGER_MANAGERS = new Set(["owner", "admin", "editor"]);
export const canStart = (role?: string | null) => !!role && STARTERS.has(role);
export const canSaveColumns = (role?: string | null) => !!role && TRIGGER_MANAGERS.has(role);

/** Whether a start can go ahead (§5.1): published, enabled, executable. */
export const startable = (w: Pick<WorkflowRow, "active_version_id" | "enabled" | "executable">) =>
  w.active_version_id !== null && w.enabled && w.executable === true;

/** A submission: its key and the body it was sent with, as JSON. */
export interface Sent {
  key: string;
  body: string;
}

/** The key a submission goes under (§5.2): the last one's when the same form is sent again (an answer lost on the
 * way), else a new one, so a changed form is never taken for a retry. */
export function keyFor(last: Sent | null, body: unknown): Sent {
  const text = JSON.stringify(body);
  return last !== null && last.body === text ? last : { key: crypto.randomUUID(), body: text };
}

/** What was typed for one version's form, kept for another's (§5.2): each value whose field still exists there with
 * the same type. */
export function keptValues(values: ReadonlyMap<string, string>, from: StartForm, to: StartForm): Map<string, string> {
  const before = new Map(from.fields.map((f) => [f.name, f]));
  return new Map(
    to.fields.flatMap((f) => {
      const prior = before.get(f.name);
      const typed = values.get(f.name);
      return prior && typed !== undefined && JSON.stringify(prior.type) === JSON.stringify(f.type) ? [[f.name, typed] as const] : [];
    }),
  );
}

/** A refused start, in words: its code, what the form says, each reason beside the field it names, and for
 * `version_changed` the version now active. */
export interface Refusal {
  code: string;
  words: string;
  fields: Record<string, string>;
  active?: { id: string; number: number };
}

const AT = /^The run's input doesn't match the workflow's input schema at (.+): it breaks `(.+)`\.$/;
const NOTHING = "Nothing started.";
const FORM_WORDS: Record<string, string> = {
  upload_expired: "The file was kept for an hour, and that hour has passed: choose it again.",
  upload_consumed: "This file already started a run: choose it again to start another.",
  upload_not_found: "The file isn't staged any more: choose it again.",
  csv_busy: `The server is busy reading other files. ${NOTHING} Start again in a moment.`,
  key_unusable: `The tenant's key can't be read while the tenant is being erased. ${NOTHING}`,
  forbidden: `Your role can't start runs. ${NOTHING}`,
  network: "The server didn't answer. Start again: the same form is never started twice.",
};

export function refusalOf(e: unknown): Refusal {
  if (!(e instanceof ApiError)) return { code: "network", words: FORM_WORDS.network!, fields: {} };
  const body = (e.body ?? {}) as { messages?: unknown; active_version_id?: unknown; active_version_number?: unknown };
  const messages = Array.isArray(body.messages) ? body.messages.filter((m): m is string => typeof m === "string") : [];
  if (e.code === "version_changed" && typeof body.active_version_id === "string" && typeof body.active_version_number === "number") {
    const n = body.active_version_number;
    return {
      code: e.code, fields: {}, active: { id: body.active_version_id, number: n },
      words: `Version ${n} was published while this was open. ${NOTHING} The form now shows version ${n}'s input, with your values kept where they still fit: check them and start again.`,
    };  // prettier-ignore
  }
  if (e.code === "input_invalid") {
    const fields: Record<string, string> = {};
    const rest: string[] = [];
    for (const m of messages) {
      const at = AT.exec(m);
      if (at && at[1] !== "its root") fields[`field:${at[1]!.split(".")[0]!}`] = `Doesn't fit the input: it breaks \`${at[2]!}\`.`;
      else rest.push(at ? `At its root: it breaks \`${at[2]!}\`.` : m);
    }
    return { code: e.code, fields, words: ["The input doesn't fit the workflow's input.", NOTHING, ...rest].join(" ") };
  }
  const own = Object.hasOwn(FORM_WORDS, e.code) ? FORM_WORDS[e.code]! : null;
  return { code: e.code, fields: {}, words: own ?? `${reasonWords(e.code) ?? (messages.join(" ") || "It was refused.")} ${NOTHING}` };
}

/** Why a file can't be read (§5.3), after its name: the server names no header, a file's text never in an answer. */
export function fileWords(code: string, limits: { max_rows: number; max_bytes: number }): string {
  switch (code) {
    case "csv_encoding":
      return "isn't UTF-8 text";
    case "csv_empty":
      return "has no header or rows";
    case "csv_duplicate_header":
      return "has two columns with the same name";
    case "csv_malformed":
      return "has a quote that isn't closed, or a cell split across lines";
    case "csv_too_many_rows":
      return `has more than ${limits.max_rows.toLocaleString("en-US")} rows, this workflow's limit`;
    case "too_large":
    case "csv_too_large":
      return `is over ${mbOf(limits.max_bytes)} MB, this workflow's limit`;
    default:
      return "can't be read";
  }
}

const CELL_WORDS: Record<string, string> = {
  required: "Missing: a value is required",
  cell_count: "Has more or fewer cells than the header",
  not_integer: "Not a whole number",
  out_of_range: "Out of range",
  not_number: "Not a number",
  not_boolean: "Not true or false (true, yes, 1; false, no, 0)",
  not_mac: "Not a MAC address",
  not_ip: "Not an IP address",
  not_cidr: "Not a network in CIDR form",
  not_in_enum: "Not one of the allowed values",
};
/** A row's problem with a cell (or the record as a whole), in words. */
export const cellWords = (code: string) => (Object.hasOwn(CELL_WORDS, code) ? CELL_WORDS[code]! : `Breaks a rule (${code})`);

const MAPPING_WORDS: Record<string, string> = {
  required_unmapped: "Required: choose the file's column for it.",
  unknown_header: "The file has no such column.",
  header_reused: "Another column already comes from this one.",
  unknown_column: "This version doesn't read this column.",
};
/** What keeps a column's choice from building rows, in words. */
export const mappingWords = (code: string) => (Object.hasOwn(MAPPING_WORDS, code) ? MAPPING_WORDS[code]! : `Can't be used (${code})`);
