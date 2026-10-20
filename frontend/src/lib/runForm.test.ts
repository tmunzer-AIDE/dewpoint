// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import {
  canSaveColumns, canStart, cellWords, fileWords, holds, keptValues, keyFor, mappingWords, previewCsv, refusalOf, rerunRun,
  saveColumns, staleWords, startRun, startable, uploadCsv, uploadProblem, type StartForm,
} from "./runForm";  // prettier-ignore

let sent: Request[];
let bodies: string[];
beforeEach(() => {
  sent = [];
  bodies = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    sent.push(request);
    bodies.push(await request.clone().text());
    return new Response(JSON.stringify({ id: "r1" }), { status: 202 });
  });
});
afterEach(() => vi.restoreAllMocks());

const field = (name: string, type: string, over: object = {}) => ({ name, type, required: false, sensitive: false, ...over });
const form = (fields: object[], over: Partial<StartForm> = {}): StartForm =>
  ({ workflow_id: "w1", version_id: "v7", version_number: 7, published_at: "2026-10-20T09:12:00Z", published_by: null, fields, csv: null, ...over }) as StartForm;

describe("the run form's calls (the run form design §5.2, §5.3)", () => {
  it("starts a run on the version it confirmed, under the submission's key", async () => {
    await startRun("t1", "w1", { input: { site: "HQ" }, mode: "live", expected_version_id: "v7" }, "k1");
    expect(new URL(sent[0]!.url).pathname).toBe("/api/v1/t/t1/workflows/w1/runs");
    expect(sent[0]!.headers.get("Idempotency-Key")).toBe("k1");
    expect(JSON.parse(bodies[0]!)).toEqual({ input: { site: "HQ" }, mode: "live", expected_version_id: "v7" });
  });

  it("re-runs a run through its own route, under the submission's key", async () => {
    await rerunRun("t1", "r0", { mode: "simulate", expected_version_id: "v7" }, "k2");
    expect(new URL(sent[0]!.url).pathname).toBe("/api/v1/t/t1/runs/r0/rerun");
    expect(sent[0]!.headers.get("Idempotency-Key")).toBe("k2");
    expect(JSON.parse(bodies[0]!)).toEqual({ mode: "simulate", expected_version_id: "v7" });
  });

  it("uploads a file as it is, as text/csv, never as JSON", async () => {
    await uploadCsv("t1", "w1", new File(["Site\nHQ\n"], "sites.csv", { type: "text/csv" }));
    expect(new URL(sent[0]!.url).pathname).toBe("/api/v1/t/t1/workflows/w1/csv-uploads");
    expect(sent[0]!.headers.get("Content-Type")).toBe("text/csv");
    expect(bodies[0]).toBe("Site\nHQ\n");
  });

  it("checks a staged file again under other columns, and saves the columns", async () => {
    await previewCsv("t1", "w1", "u1", { site: "Site" });
    await saveColumns("t1", "w1", { site: "Site" });
    expect(sent.map((r) => [r.method, new URL(r.url).pathname])).toEqual([
      ["POST", "/api/v1/t/t1/workflows/w1/csv-uploads/u1/preview"],
      ["PUT", "/api/v1/t/t1/workflows/w1/csv-mapping"],
    ]);
    expect(bodies.map((b) => JSON.parse(b) as unknown)).toEqual([{ mapping: { site: "Site" } }, { mapping: { site: "Site" } }]);
  });
});

describe("who may start, and what can start (§5.1)", () => {
  it("shows Start to the roles that hold run.start, and the columns' saving to those that manage triggers", () => {
    expect(["viewer", "operator", "editor", "admin", "owner", undefined].map(canStart)).toEqual([false, true, true, true, true, false]);
    expect(["viewer", "operator", "editor", "admin", "owner", undefined].map(canSaveColumns)).toEqual([false, false, true, true, true, false]);
  });

  it("offers a start only where it can go ahead: published, enabled, executable", () => {
    const w = { active_version_id: "v7", enabled: true, executable: true };
    expect([w, { ...w, active_version_id: null }, { ...w, enabled: false }, { ...w, executable: false }, { ...w, executable: null }].map(startable))
      .toEqual([true, false, false, false, false]);  // prettier-ignore
  });
});

describe("one key per submitted form (§5.2)", () => {
  it("sends the same form again under the same key, and a changed one under a new key", () => {
    const first = keyFor(null, { input: { site: "HQ" } });
    expect(keyFor(first, { input: { site: "HQ" } })).toBe(first);
    const changed = keyFor(first, { input: { site: "Lyon" } });
    expect(changed.key).not.toBe(first.key);
  });
});

describe("a newer version's form (§5.2)", () => {
  it("keeps each value whose field still exists with the same type, and drops the rest", () => {
    const before = form([field("site", "string"), field("floor", "integer"), field("note", "string")]);
    const after = form([field("site", "string"), field("floor", "string"), field("vlan", "integer")], { version_id: "v8", version_number: 8 });
    const typed = new Map([["site", "HQ"], ["floor", "2"], ["note", "x"]]);
    expect([...keptValues(typed, before, after)]).toEqual([["site", "HQ"]]);
  });
});

const refused = (status: number, body: object) => new ApiError(status, (body as { error: string }).error, body);

describe("what a refused start says (§5.2, §5.3)", () => {
  it("names the version published meanwhile", () => {
    const r = refusalOf(refused(409, { error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }));
    expect(r.code).toBe("version_changed");
    expect(r.active).toEqual({ id: "v8", number: 8 });
    expect(r.words).toBe(
      "Version 8 was published while this was open. Nothing started. The form now shows version 8's input, with your values kept where they still fit: check them and start again.",
    );
  });

  it("puts an input's reasons beside the fields shown, and the others above the buttons, saying where", () => {
    const e = refused(422, { error: "input_invalid", messages: [
      "The run's input doesn't match the workflow's input schema at floor.0: it breaks `type`.",
      "The run's input doesn't match the workflow's input schema at vlan: it breaks `maximum`.",
      "The run's input doesn't match the workflow's input schema at its root: it breaks `required`.",
    ] });  // prettier-ignore
    const r = refusalOf(e, new Set(["floor", "site"]));
    expect(r.fields).toEqual({ "field:floor": "Doesn't fit the input: it breaks `type`." });
    expect(r.words).toBe("The input doesn't fit the workflow's input. Nothing started. At vlan: it breaks `maximum`. At its root: it breaks `required`.");
    expect(refusalOf(e).fields).toEqual({}); // as JSON: every reason above, with where it is
  });

  it("words a CSV upload's end, and falls back to 4e-1's words, then the server's", () => {
    expect(refusalOf(refused(410, { error: "upload_expired" })).words).toBe("The file was kept for an hour, and that hour has passed: choose it again.");
    expect(refusalOf(refused(409, { error: "upload_consumed" })).words).toBe("This file already started a run: choose it again to start another.");
    expect(refusalOf(refused(409, { error: "workflow_disabled", messages: ["The workflow is disabled."] })).words).toBe("The workflow is disabled. Nothing started.");
    expect(refusalOf(refused(409, { error: "a_new_code", messages: ["Its words."] })).words).toBe("Its words. Nothing started.");
    expect(refusalOf(new TypeError("Failed to fetch")).code).toBe("network");
  });
});

describe("a CSV file's words (§5.3)", () => {
  it("says why a file can't be read, with the workflow's limits", () => {
    const limits = { max_rows: 10_000, max_bytes: 5 * 1024 * 1024 };
    expect(fileWords("csv_duplicate_header", limits)).toBe("has two columns with the same name");
    expect(fileWords("csv_too_many_rows", limits)).toBe("has more than 10,000 rows, this workflow's limit");
    expect(fileWords("too_large", limits)).toBe("is over 5 MB, this workflow's limit");
    expect(fileWords("something_new", limits)).toBe("can't be read");
  });

  it("words each row's problem, and each column's", () => {
    expect(["required", "cell_count", "not_in_enum", "not_boolean"].map(cellWords)).toEqual([
      "Missing: a value is required", "Has more or fewer cells than the header", "Not one of the allowed values",
      "Not true or false (true, yes, 1; false, no, 0)",
    ]);  // prettier-ignore
    expect(mappingWords("required_unmapped")).toBe("Required: choose the file's column for it.");
  });
});

describe("a CSV file's columns and problems, in words (§5.3; the CsvStates and MoreStates boards)", () => {
  const limits = { max_rows: 10_000, max_bytes: 5 * 1024 * 1024 };
  it("says what a file can't be, by its name, and what to do", () => {
    expect(uploadProblem("sites.csv", refused(422, { error: "csv_duplicate_header" }), limits)).toEqual({
      words: "sites.csv can't be read: it has two columns with the same name. Rename one and choose the file again.", code: "csv_duplicate_header",
    });  // prettier-ignore
    expect(uploadProblem("all.csv", refused(413, { error: "too_large" }), limits).words).toBe("all.csv is over 5 MB, this workflow's limit. Split it, or keep only the rows to run.");
    expect(uploadProblem("all.csv", refused(503, { error: "csv_busy" }), limits).words).toBe(
      "The server is busy reading other files. Nothing was kept. Choose the file again in a moment.",
    );
    expect(uploadProblem("a.csv", new TypeError("Failed to fetch"), limits)).toEqual({ words: "The server didn't answer: a.csv wasn't read. Choose it again.", code: null });
    expect(uploadProblem("a.csv", refused(409, { error: "workflow_disabled", messages: ["…"] }), limits).words).toBe("a.csv wasn't read. The workflow is disabled.");
  });

  it("says what each column holds", () => {
    const col = (type: string, over: object = {}) => ({ header: "H", name: "h", type, required: false, sensitive: false, ...over });
    expect(holds(col("string"))).toBe("Text");
    expect(holds(col("integer"))).toBe("A whole number");
    expect(holds(col("ip"))).toBe("An IP address");
    expect(holds(col("enum", { values: ["FR", "DE", "ES", "IT", "GB", "US", "NL"] }))).toBe("One of a list: FR, DE, ES, IT, GB, US…");
    expect(holds(col("enum", { values: ["FR", "DE"] }))).toBe("One of a list: FR, DE");
  });

  it("says why the saved columns no longer fit", () => {
    expect(staleWords(7, [{ column: "site_ref", code: "unknown_column" }, { column: "name", code: "required_unmapped" }])).toBe(
      "The columns saved for this workflow no longer fit version 7: it doesn't read site_ref any more, and it needs name, which they leave out. The file's columns with the same names are proposed instead; check them.",
    );
  });
});
