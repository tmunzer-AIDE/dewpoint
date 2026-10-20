// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onAnnounce } from "../../lib/announce";
import type { CsvPreview, CsvUpload, StartForm } from "../../lib/runForm";
import { local } from "../../test/runs";
import { RunForm } from "./RunForm";

// The CsvStates board's workflow: five columns, two required.
const COLUMNS = [
  { header: "Site name", name: "name", type: "string", required: true, sensitive: false },
  { header: "Country", name: "country_code", type: "enum", required: true, sensitive: false, values: ["FR", "DE", "ES", "IT", "GB", "US", "NL"] },
  { header: "address", name: "address", type: "string", required: false, sensitive: false },
  { header: "Gateway", name: "gateway_ip", type: "ip", required: false, sensitive: false },
  { header: "VLAN", name: "vlan_id", type: "integer", required: false, sensitive: false },
];  // prettier-ignore
const FORM: StartForm = {
  workflow_id: "w1", version_id: "v7", version_number: 7, published_at: local(9, 12, 0), published_by: "nadia@corp.test", fields: [],
  csv: { max_rows: 10_000, max_bytes: 5 * 1024 * 1024, columns: COLUMNS },
};  // prettier-ignore
const HEADERS = ["Site name", "Country", "address", "Gateway", "Notes", "Region"];
const SAVED = { name: "Site name", country_code: "Country", address: "address", gateway_ip: "Gateway" };
/** A file checked under its columns: every row passes unless `over` says otherwise. */
const described = (over: Partial<CsvPreview> = {}): CsvPreview => ({
  version_id: "v7", mapping: SAVED, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0, error_groups: [],
  rows_with_errors: 0, ...over,
});  // prettier-ignore
/** An upload's answer. */
const upload = (over: Partial<CsvUpload> = {}): CsvUpload => ({
  ...described(), upload_id: "u1", expires_at: local(11, 0, 0), headers: HEADERS, row_count: 2431, default_mapping: { status: "applied" }, ...over,
});  // prettier-ignore
// The Errors board's file: 37 errors in 29 rows.
const ERRORS: Partial<CsvPreview> = {
  error_count: 37, rows_with_errors: 29,
  error_groups: [
    { column: "country_code", code: "not_in_enum", count: 21, rows: [7, 19, 33, 48, 52] },
    { column: "gateway_ip", code: "not_ip", count: 10, rows: [12, 13, 14, 15, 16] },
    { column: null, code: "cell_count", count: 6, rows: [102, 140, 141, 150, 151] },
  ],
  errors: [{ row: 7, column: "country_code", code: "not_in_enum" }, { row: 102, column: null, code: "cell_count" }],
};  // prettier-ignore

let uploads: { type: string | null; body: string }[];
let starts: unknown[];
let writes: string[]; // "METHOD path" of each write, in order
let previews: { mapping: unknown; answer: (r: Response) => void }[]; // each check asked, in order
let held: boolean; // previews wait for the test to answer them
let previewAnswer: (mapping: Record<string, string>) => Response;
let startAnswers: (() => Response)[];
let saveAnswer: () => Response;
let forms: StartForm[];
let role: string;
let uploadAnswer: () => Promise<Response>;
let said: string[];
let stop: () => void;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  uploads = [];
  starts = [];
  writes = [];
  previews = [];
  held = false;
  previewAnswer = (mapping) => json(described({ mapping }));
  startAnswers = [];
  saveAnswer = () => json({ version_id: "v7", mapping: SAVED });
  forms = [FORM];
  role = "operator";
  said = [];
  uploadAnswer = () => Promise.resolve(json(upload(), 201));
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
  stop = onAnnounce((m) => said.push(m));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(forms.length > 1 ? forms.shift() : forms[0]);
    if (path === "/api/v1/t/t1") return json({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role });
    if (request.method !== "GET") writes.push(`${request.method} ${path}`);
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads/u1/preview") {
      const { mapping } = JSON.parse(await request.text()) as { mapping: Record<string, string> };
      if (!held) {
        previews.push({ mapping, answer: () => undefined });
        return previewAnswer(mapping);
      }
      return new Promise<Response>((answer) => previews.push({ mapping, answer }));
    }
    if (request.method === "PUT" && path === "/api/v1/t/t1/workflows/w1/csv-mapping") return saveAnswer();
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads") {
      uploads.push({ type: request.headers.get("Content-Type"), body: await request.text() });
      return uploadAnswer();
    }
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/runs") {
      starts.push(JSON.parse(await request.text()));
      return (startAnswers.shift() ?? (() => json({ id: "r1" }, 202)))();
    }
    return json({ error: "not_found" }, 404);
  });
});
afterEach(() => {
  stop();
  vi.restoreAllMocks();
});

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RunForm tenantId="t1" workflow={{ id: "w1", name: "Bulk site creation" }} onStarted={vi.fn()} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}
const FILE = () => new File(["Site name,Country\nLyon,FR\n"], "sites-q4.csv", { type: "text/csv" });
async function choose(file = FILE()) {
  const user = userEvent.setup();
  await user.upload(await screen.findByLabelText("Choose a file"), file);
  return user;
}
/** The columns' table, row by row: the column, the file's column chosen, how it was proposed. */
const columnRows = () =>
  within(screen.getByRole("region", { name: "Columns" })).getAllByRole("row").slice(1).map((r) => {
    const select = within(r).getByRole<HTMLSelectElement>("combobox");
    return [r.querySelector("th")?.textContent, select.selectedOptions[0]?.textContent, r.querySelector("td:last-child")?.textContent];
  });  // prettier-ignore

describe("a CSV workflow's file (the run form design §5.3; the CsvStates board)", () => {
  it("says what it reads and its limits before a file, and Start waits for one", async () => {
    show();
    expect(await screen.findByText("This workflow starts from a CSV file: one run, one pass of its loop per row.")).toBeTruthy();
    expect(screen.getByText("Up to 10,000 rows and 5 MB · comma, semicolon or tab separated · UTF-8")).toBeTruthy();
    const reads = within(screen.getByRole("region", { name: "The columns it reads" })).getAllByRole("row").slice(1);
    expect(reads.map((r) => [...r.querySelectorAll("th, td")].map((c) => c.textContent))).toEqual([
      ["Site name requiredname", "Text"],
      ["Country requiredcountry_code", "One of a list: FR, DE, ES, IT, GB, US…"],
      ["address", "Text"],
      ["Gatewaygateway_ip", "An IP address"],
      ["VLANvlan_id", "A whole number"],
    ]);
    const start = screen.getByRole("button", { name: "Start the live run" });
    expect(start).toHaveProperty("disabled", true);
    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("Choose a file first.");
  });

  it("uploads the file as it is, says it's reading, then proposes the file's columns, saying how", async () => {
    let answer!: (r: Response) => void;
    uploadAnswer = () => new Promise((r) => (answer = r));
    show();
    await choose();
    expect(uploads).toEqual([{ type: "text/csv", body: "Site name,Country\nLyon,FR\n" }]);
    expect(screen.getByText("sites-q4.csv · 1 KB")).toBeTruthy();
    expect(said).toContain("Reading the file…");
    answer(json(upload(ERRORS), 201)); // rows to fix: the columns stay open
    expect(await screen.findByText("sites-q4.csv · 2,431 rows · 6 columns")).toBeTruthy();
    expect(columnRows()).toEqual([
      ["Site name requiredname", "Site name", "saved"],
      ["Country requiredcountry_code", "Country", "saved"],
      ["address", "address", "saved"],
      ["Gatewaygateway_ip", "Gateway", "saved"],
      ["VLANvlan_id", "Not used", "left out"],
    ]);
    expect(screen.getByLabelText("Choose another file")).toBeTruthy();
  });

  it("starts with the staged file and its columns, never skipping a row", async () => {
    show();
    const user = await choose();
    await screen.findByText("sites-q4.csv · 2,431 rows · 6 columns");
    await user.click(screen.getByRole("button", { name: /^Start the live run/ }));
    expect(starts).toEqual([{ input: {}, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: SAVED } }]);
  });

  it("says the file's columns with the same names are proposed when none are saved", async () => {
    uploadAnswer = () => Promise.resolve(json(upload({ default_mapping: { status: "none" }, mapping: { address: "address" } }), 201));
    show();
    await choose();
    await screen.findByRole("region", { name: "Columns" });
    expect(columnRows().map((r) => r[2])).toEqual(["left out", "left out", "same name", "left out", "left out"]);
  });

  it("says a file can't be read, why, with its code, and asks for another", async () => {
    uploadAnswer = () => Promise.resolve(json({ error: "csv_duplicate_header", messages: ["…"] }, 422));
    show();
    await choose();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("sites-q4.csv can't be read: it has two columns with the same name. Rename one and choose the file again. csv_duplicate_header");
    expect(screen.getByLabelText("Choose a file")).toBeTruthy();
    expect(screen.getByRole("region", { name: "The columns it reads" })).toBeTruthy();
  });

  it("says the server is busy, keeping nothing", async () => {
    uploadAnswer = () => Promise.resolve(json({ error: "csv_busy", messages: ["…"] }, 503));
    show();
    await choose();
    expect((await screen.findByRole("alert")).textContent).toBe("The server is busy reading other files. Nothing was kept. Choose the file again in a moment. csv_busy");
  });

  it("says the saved columns no longer fit this version, the same names proposed instead (the MoreStates board)", async () => {
    uploadAnswer = () => Promise.resolve(json(upload({ default_mapping: { status: "stale", problems: [{ column: "site_ref", code: "unknown_column" }] } }), 201));
    show();
    await choose();
    expect(
      await screen.findByText(
        "The columns saved for this workflow no longer fit version 7: it doesn't read site_ref any more. The file's columns with the same names are proposed instead; check them.",
      ),
    ).toBeTruthy();
  });

  it("marks a required column without the file's column, and checks no row until it has one (the MoreStates board)", async () => {
    const partial = { name: "Site name", address: "address", gateway_ip: "Gateway" }; // no Country
    uploadAnswer = () => Promise.resolve(json(upload({ mapping: partial, problems: [{ column: "country_code", code: "required_unmapped" }] }), 201));
    show();
    await choose();
    const select = await screen.findByRole("combobox", { name: "Country, from the file's column" });
    expect((select as HTMLSelectElement).selectedOptions[0]?.textContent).toBe("Choose a column");
    expect(document.getElementById(select.getAttribute("aria-describedby")!)?.textContent).toBe("Required: choose the file's column for it.");
    expect(screen.getByText("No row is checked until every required column is mapped.")).toBeTruthy();
  });

  it("says beside a column that the file has no such column", async () => {
    uploadAnswer = () => Promise.resolve(json(upload({ mapping: { ...SAVED, gateway_ip: "GW" }, problems: [{ column: "gateway_ip", code: "unknown_header" }] }), 201));
    show();
    await choose();
    const select = await screen.findByRole("combobox", { name: "Gateway, from the file's column" });
    expect((select as HTMLSelectElement).selectedOptions[0]?.textContent).toBe("GW");
    expect(document.getElementById(select.getAttribute("aria-describedby")!)?.textContent).toBe("The file has no such column.");
  });
});

describe("a CSV file checked (the run form design §5.3; the CsvStates and MoreStates boards)", () => {
  const pick = async (user: ReturnType<typeof userEvent.setup>, column: string, header: string) =>
    user.selectOptions(await screen.findByRole("combobox", { name: `${column}, from the file's column` }), header); // once the upload's answer is drawn

  it("checks every row again when a column changes, one check at a time, the last change's", async () => {
    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
    held = true;
    show();
    const user = await choose();
    await pick(user, "Gateway", "Notes");
    expect(previews.map((p) => p.mapping)).toEqual([{ ...SAVED, gateway_ip: "Notes" }]);
    expect(screen.getByText("Checking every row again with these columns…")).toBeTruthy();
    expect(said).toContain("Checking every row again with these columns…");
    const start = screen.getByRole("button", { name: "Start the live run" });
    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("The rows are being checked.");
    await pick(user, "VLAN", "Region");
    await pick(user, "address", "Not used");
    expect(previews).toHaveLength(1); // one at a time
    previews[0]!.answer(json(described({ mapping: { ...SAVED, gateway_ip: "Notes" }, ...ERRORS })));
    await vi.waitFor(() => expect(previews).toHaveLength(2));
    const last = { name: "Site name", country_code: "Country", gateway_ip: "Notes", vlan_id: "Region" }; // address: Not used
    expect(previews[1]!.mapping).toEqual(last); // the last change's only, never the one between
    expect(screen.queryByText(/errors in/)).toBeNull(); // the first answer is already old
    previews[1]!.answer(json(described({ mapping: last })));
    expect(await screen.findByText("All 2,431 rows pass.")).toBeTruthy();
    expect(said).toContain("All 2,431 rows pass.");
  });

  it("gives the errors at a glance: the counts, each column's problem with its first rows, and every error row by row", async () => {
    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
    show();
    await choose();
    expect(await screen.findByText("37 errors in 29 of 2,431 rows")).toBeTruthy();
    expect(said).toContain("37 errors in 29 of 2,431 rows");
    expect(screen.getByText("The run can't start until every row passes. Fix the file, then choose it again.")).toBeTruthy();
    const groups = within(screen.getByRole("region", { name: "Errors by column" })).getAllByRole("row").slice(1);
    expect(groups.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
      ["Country", "Not one of the allowed values", "21 · 7, 19, 33, 48, 52 and 16 more"],
      ["Gateway", "Not an IP address", "10 · 12, 13, 14, 15, 16 and 5 more"],
      ["The whole row", "Has more or fewer cells than the header", "6 · 102, 140, 141, 150, 151 and 1 more"],
    ]);
    await userEvent.click(screen.getByText("Every error, row by row (37)"));
    const listed = within(screen.getByRole("region", { name: "Every error, row by row" })).getAllByRole("row").slice(1);
    expect(listed.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
      ["7", "Country", "Not one of the allowed values"],
      ["102", "The whole row", "Has more or fewer cells than the header"],
    ]);
    const start = screen.getByRole("button", { name: "Start the live run" });
    expect(start).toHaveProperty("disabled", true);
    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("Every row must pass first.");
    expect(screen.queryByText(/^Above 100 errors/)).toBeNull();
  });

  it("says when only the first 100 errors are listed", async () => {
    const errors = Array.from({ length: 100 }, (_, i) => ({ row: i + 1, column: "gateway_ip", code: "not_ip" }));
    uploadAnswer = () => Promise.resolve(json(upload({ ...ERRORS, error_count: 150, errors }), 201));
    show();
    await choose();
    expect(await screen.findByText("Above 100 errors, the first 100 are listed row by row; the counts above are of every error.")).toBeTruthy();
  });

  it("previews the first rows as written once every row passes, folds the columns, and Start says how many rows", async () => {
    const preview = [{ row: 1, cells: { name: "Lyon Part-Dieu", country_code: "FR", address: "17 Rue du Docteur Bouchut", gateway_ip: "10.40.1.1" } }];
    uploadAnswer = () => Promise.resolve(json(upload({ preview, masked_columns: ["psk"] }), 201));
    show();
    const user = await choose();
    expect(await screen.findByText("All 2,431 rows pass.")).toBeTruthy();
    const rows = within(screen.getByRole("region", { name: "The file's first 5 rows, under these columns" })).getAllByRole("row");
    expect(rows.map((r) => [...r.querySelectorAll("th, td")].map((c) => c.textContent))).toEqual([
      ["#", "Site name", "Country", "address", "Gateway"],
      ["1", "Lyon Part-Dieu", "FR", "17 Rue du Docteur Bouchut", "10.40.1.1"],
    ]);
    expect(screen.getByText("A column marked sensitive is never shown here.")).toBeTruthy();
    expect(screen.getByText("Columns: 4 of 5 mapped, as saved · VLAN not used")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Columns" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByRole("region", { name: "Columns" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start the live run · 2,431 rows" })).toHaveProperty("disabled", false);
    await user.click(screen.getByRole("radio", { name: "Simulated" }));
    expect(screen.getByRole("button", { name: "◌ Start the simulation · 2,431 rows" })).toBeTruthy();
  });

  it("saves the columns for the workflow's next CSV before the start, when asked, for the roles that manage triggers", async () => {
    role = "editor";
    show();
    const user = await choose();
    await user.click(await screen.findByRole("checkbox", { name: "Save these columns for this workflow's next CSV" }));
    await user.click(screen.getByRole("button", { name: "Start the live run · 2,431 rows" }));
    await vi.waitFor(() => expect(writes).toEqual(["POST /api/v1/t/t1/workflows/w1/csv-uploads", "PUT /api/v1/t/t1/workflows/w1/csv-mapping", "POST /api/v1/t/t1/workflows/w1/runs"]));
  });

  it("starts nothing when the columns couldn't be saved", async () => {
    role = "editor";
    saveAnswer = () => json({ error: "internal_error" }, 500);
    show();
    const user = await choose();
    await user.click(await screen.findByRole("checkbox", { name: "Save these columns for this workflow's next CSV" }));
    await user.click(screen.getByRole("button", { name: "Start the live run · 2,431 rows" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The columns couldn't be saved, so nothing started. Start again, or leave them unsaved.");
    expect(starts).toEqual([]);
  });

  it("offers an operator no saving of the columns", async () => {
    show();
    await choose();
    await screen.findByText("All 2,431 rows pass.");
    expect(screen.queryByRole("checkbox", { name: /Save these columns/ })).toBeNull();
  });

  it("asks for the file again when its hour has passed, or a start already used it", async () => {
    startAnswers = [() => json({ error: "upload_expired", messages: ["…"] }, 410)];
    show();
    const user = await choose();
    await user.click(await screen.findByRole("button", { name: "Start the live run · 2,431 rows" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The file was kept for an hour, and that hour has passed: choose it again. upload_expired");
    expect(screen.getByLabelText("Choose a file")).toBeTruthy();
  });

  it("says when the rows couldn't be checked again, and Start waits for a check", async () => {
    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
    previewAnswer = () => json({ error: "internal_error", messages: ["…"] }, 500);
    show();
    const user = await choose();
    await pick(user, "Gateway", "Notes");
    expect(await screen.findByText("The rows couldn't be checked again with these columns. Change a column to check them again.")).toBeTruthy();
    const start = screen.getByRole("button", { name: "Start the live run" });
    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("The rows must be checked first.");
  });

  it("asks for the file again when a check finds it already used", async () => {
    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
    previewAnswer = () => json({ error: "upload_consumed", messages: ["…"] }, 409);
    show();
    const user = await choose();
    await pick(user, "Gateway", "Notes");
    expect((await screen.findByRole("alert")).textContent).toBe("This file already started a run: choose it again to start another. upload_consumed");
  });

  it("shows a version published since the form opened, keeping the file and the columns it still reads, and checks again", async () => {
    const NEWER: StartForm = { ...FORM, version_id: "v8", version_number: 8, csv: { ...FORM.csv!, columns: COLUMNS.filter((c) => c.name !== "gateway_ip") } };
    forms = [FORM, NEWER];
    uploadAnswer = () => Promise.resolve(json(upload({ version_id: "v8" }), 201));
    previewAnswer = (mapping) => json(described({ version_id: "v8", mapping }));
    show();
    await choose();
    expect((await screen.findByRole("alert")).textContent).toMatch(/^Version 8 was published while this was open\./);
    await vi.waitFor(() => expect(previews.map((c) => c.mapping)).toEqual([{ name: "Site name", country_code: "Country", address: "address" }]));
    expect(await screen.findByText((_, el) => el?.tagName === "P" && el.textContent === "Version 8 · published today 09:12:00 by nadia@corp.test")).toBeTruthy();
    expect(await screen.findByText("All 2,431 rows pass.")).toBeTruthy();
    expect(screen.getByText("Columns: 3 of 4 mapped, as saved · VLAN not used")).toBeTruthy();
  });

  it("checks the file again under the version a refused start names, its upload unused", async () => {
    const NEWER: StartForm = { ...FORM, version_id: "v8", version_number: 8 };
    forms = [FORM, NEWER];
    startAnswers = [() => json({ error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }, 409)];
    previewAnswer = (mapping) => json(described({ version_id: "v8", mapping }));
    show();
    const user = await choose();
    await user.click(await screen.findByRole("button", { name: "Start the live run · 2,431 rows" }));
    await vi.waitFor(() => expect(previews.map((c) => c.mapping)).toEqual([SAVED]));
    await user.click(await screen.findByRole("button", { name: "Start the live run · 2,431 rows" }));
    expect(starts).toEqual([
      { input: {}, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: SAVED } },
      { input: {}, mode: "live", expected_version_id: "v8", csv: { upload_id: "u1", mapping: SAVED } },
    ]);
  });
});

describe("a CSV file below 640 px (the run form design §5.6; the Narrow320 boards)", () => {
  beforeEach(() => {
    const wide = window.matchMedia.bind(window);
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...wide(query), matches: true }));
  });

  it("lists each column with its choice, and each problem with its rows", async () => {
    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
    show();
    await choose();
    const columns = await screen.findByRole("list", { name: "Columns" });
    expect(within(columns).getAllByRole("listitem")).toHaveLength(5);
    expect(within(columns).getByRole("combobox", { name: "Country, from the file's column" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Columns" })).toBeNull();
    const problems = within(screen.getByRole("list", { name: "Errors by column" })).getAllByRole("listitem");
    expect(problems.map((p) => [...p.querySelectorAll("p")].map((l) => l.textContent))).toEqual([
      ["Country · Not one of the allowed values", "21 rows · 7, 19, 33, 48, 52 and 16 more"],
      ["Gateway · Not an IP address", "10 rows · 12, 13, 14, 15, 16 and 5 more"],
      ["The whole row · Has more or fewer cells than the header", "6 rows · 102, 140, 141, 150, 151 and 1 more"],
    ]);
  });
});
