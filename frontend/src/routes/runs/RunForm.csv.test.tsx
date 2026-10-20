// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onAnnounce } from "../../lib/announce";
import type { CsvUpload, StartForm } from "../../lib/runForm";
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
/** An upload's answer: every row passes unless `over` says otherwise. */
const upload = (over: Partial<CsvUpload> = {}): CsvUpload => ({
  version_id: "v7", upload_id: "u1", expires_at: local(11, 0, 0), headers: HEADERS, row_count: 2431, mapping: SAVED,
  default_mapping: { status: "applied" }, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0,
  error_groups: [], rows_with_errors: 0, ...over,
});  // prettier-ignore

let uploads: { type: string | null; body: string }[];
let starts: unknown[];
let uploadAnswer: () => Promise<Response>;
let said: string[];
let stop: () => void;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  uploads = [];
  starts = [];
  said = [];
  uploadAnswer = () => Promise.resolve(json(upload(), 201));
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
  stop = onAnnounce((m) => said.push(m));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(FORM);
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads") {
      uploads.push({ type: request.headers.get("Content-Type"), body: await request.text() });
      return uploadAnswer();
    }
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/runs") {
      starts.push(JSON.parse(await request.text()));
      return json({ id: "r1" }, 202);
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
    answer(json(upload(), 201));
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
    await screen.findByRole("region", { name: "Columns" });
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
