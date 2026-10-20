// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StartForm } from "../../lib/runForm";
import type { Run } from "../../lib/runs";
import { FAILED_RUN, local } from "../../test/runs";
import { RunForm } from "./RunForm";

// The Rerun board: version 11's run, re-run on version 12; its token read back redacted.
const RUN: Run = { ...FAILED_RUN, version_id: "v11" };
const FORM: StartForm = {
  workflow_id: "w1", version_id: "v12", version_number: 12, published_at: local(9, 0, 0), published_by: null, csv: null,
  fields: [
    { name: "site", title: "Site", type: "string", required: true, sensitive: false },
    { name: "floor", title: "Floor", type: "integer", required: false, sensitive: false },
    { name: "token", title: "API token", type: "string", required: true, sensitive: true },
  ],
};  // prettier-ignore
const KEPT = { input: { site: "HQ", floor: 2, token: "[redacted]" }, read_back: "kept", seeds: null };

// A CSV run (the Rerun board's third): 2,431 rows on version 7, its other fields a region and a token.
const CSV_RUN: Run = {
  ...FAILED_RUN, id: "77e0b9d2-0000-4000-8000-000000000005", version_id: "v7",
  csv: { row_count: 2431, headers: ["Site name"], mapping: { name: "Site name" }, error_count: 0, errors: [], skipped: [] },
};  // prettier-ignore
const CSV_FORM: StartForm = {
  workflow_id: "w1", version_id: "v7", version_number: 7, published_at: local(9, 0, 0), published_by: null,
  fields: [
    { name: "region", title: "Region", type: "string", required: true, sensitive: false },
    { name: "token", title: "API token", type: "string", required: true, sensitive: true },
  ],
  csv: { max_rows: 10_000, max_bytes: 5 * 1024 * 1024, columns: [{ header: "Site name", name: "name", type: "string", required: true, sensitive: false }] },
};  // prettier-ignore
const CSV_KEPT = { input: { region: "EMEA", token: "[redacted]" }, read_back: "kept", seeds: null };
const UPLOADED = {
  version_id: "v7", upload_id: "u1", expires_at: local(11, 0, 0), headers: ["Site name"], row_count: 12, mapping: { name: "Site name" },
  default_mapping: { status: "none" }, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0, error_groups: [], rows_with_errors: 0,
};  // prettier-ignore

let input: unknown;
let form: StartForm;
let reruns: { key: string | null; body: unknown }[];
let rerunAnswers: (() => Response)[];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  input = KEPT;
  form = FORM;
  reruns = [];
  rerunAnswers = [];
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (req) => {
    const request = req as Request;
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(form);
    if (path.endsWith("/input")) return json(input);
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads") return json(UPLOADED, 201);
    if (request.method === "POST" && path.endsWith("/rerun")) {
      reruns.push({ key: request.headers.get("Idempotency-Key"), body: JSON.parse(await request.text()) as unknown });
      return (rerunAnswers.shift() ?? (() => json({ id: "r1" }, 202)))();
    }
    return json({ error: "not_found" }, 404);
  });
});
afterEach(() => vi.restoreAllMocks());

function show(run: Run = RUN, ranVersion: number | null = 11) {
  const onStarted = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RunForm tenantId="t1" workflow={{ id: "w1", name: "AP offline triage" }} rerun={{ run, ranVersion }} onStarted={onStarted} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  return { onStarted };
}
const site = () => screen.findByLabelText(/^Site/);

describe("re-running a run (the run form design §5.4; the Rerun board)", () => {
  it("names the run, and the version it runs beside the one the run ran", async () => {
    show();
    expect(await screen.findByRole("dialog", { name: "Re-run 4a2b17e0" })).toBeTruthy();
    expect(await screen.findByText("It runs version 12, the one published now. Run 4a2b17e0 ran version 11.")).toBeTruthy();
  });

  it("says when it runs the same version as the run", async () => {
    show({ ...RUN, version_id: "v12" }, 12);
    expect(await screen.findByText("It runs version 12, the same version as run 4a2b17e0.")).toBeTruthy();
  });

  it("preselects the run's mode", async () => {
    show({ ...RUN, mode: "simulate" });
    await site();
    expect(screen.getByRole("radio", { name: "Simulated" })).toHaveProperty("checked", true);
    expect(screen.getByRole("button", { name: "◌ Re-run as a simulation" })).toBeTruthy();
  });

  it("prefills the original's input, keeps its protected values, and sends no input untouched: the original goes back whole", async () => {
    const { onStarted } = show();
    expect(await site()).toHaveProperty("value", "HQ");
    expect(screen.getByLabelText(/^Floor/)).toHaveProperty("value", "2");
    expect(screen.getByText("The original run's input. Change what you need.")).toBeTruthy();
    expect(screen.getByText("Kept from the original run")).toBeTruthy();
    expect(screen.queryByLabelText(/^API token/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
    expect(reruns).toEqual([{ key: expect.any(String) as string, body: { mode: "live", expected_version_id: "v12" } }]);
    expect(onStarted).toHaveBeenCalledWith("r1");
  });

  it("sends a changed input whole, its protected values entered again, never the marker", async () => {
    show();
    const user = userEvent.setup();
    await user.type(await site(), " north");
    expect(screen.getByText("Changed from the original run's input.")).toBeTruthy();
    const token = screen.getByLabelText(/^API token/);
    expect(token).toHaveProperty("value", "");
    expect(token).toHaveProperty("type", "password");
    expect(screen.getByText("Enter it again: a changed input is sent whole, and the original's protected values never reach this form.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Re-run live" }));
    expect(screen.getByText("Give a value: the input requires it.")).toBeTruthy();
    expect(reruns).toEqual([]);
    await user.type(token, "s3cret");
    await user.click(screen.getByRole("button", { name: "Re-run live" }));
    expect(reruns.map((r) => r.body)).toEqual([{ input: { site: "HQ north", floor: 2, token: "s3cret" }, mode: "live", expected_version_id: "v12" }]);
  });

  it("keeps any value that read back holding the marker, a field not marked sensitive too, and empties it once changed; an undeclared one is never sent", async () => {
    const meta = { name: "meta", title: "Meta", type: "object", required: false, sensitive: false };
    const note = { name: "note", title: "Note", type: "string", required: false, sensitive: false };
    vi.mocked(globalThis.fetch).mockImplementation(async (req) => {
      const request = req as Request;
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/t/t1/workflows/w1/start-form") return json({ ...FORM, fields: [FORM.fields[0], meta, note] });
      if (path === `/api/v1/t/t1/runs/${RUN.id}/input`) return json({ ...KEPT, input: { site: "HQ", meta: { key: "[redacted]", n: 1 }, note: "[redacted]", extra: "[redacted]" } });
      if (request.method === "POST") reruns.push({ key: null, body: JSON.parse(await request.text()) as unknown });
      return json({ id: "r1" }, 202);
    });
    show();
    await site();
    expect(screen.getAllByText("Kept from the original run")).toHaveLength(2);
    await userEvent.type(await site(), "!");
    expect(screen.getByLabelText(/^Meta/)).toHaveProperty("value", "");
    expect(screen.getByLabelText(/^Note/)).toHaveProperty("value", "");
    await userEvent.type(screen.getByLabelText(/^Meta/), "{{}");
    await userEvent.type(screen.getByLabelText(/^Note/), "n");
    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
    expect(reruns.map((r) => r.body)).toEqual([{ input: { site: "HQ!", meta: {}, note: "n" }, mode: "live", expected_version_id: "v12" }]);
  });

  it("says a reason at a field it keeps above the buttons, with where it is (the final review)", async () => {
    rerunAnswers = [() => json({ error: "input_invalid", messages: ["The run's input doesn't match the workflow's input schema at token: it breaks `minLength`."] }, 422)];
    show();
    await site();
    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "The input doesn't fit the workflow's input. Nothing started. At token: it breaks `minLength`. input_invalid",
    );
  });

  it("keeps a value its field can't show, and asks for it again once the input changes (the final review)", async () => {
    input = { ...KEPT, input: { site: "HQ\nnorth wing", floor: 2, token: "[redacted]" } };
    show();
    expect(await screen.findAllByText("Kept from the original run")).toHaveLength(2);
    expect(screen.queryByLabelText(/^Site/)).toBeNull();
    await userEvent.type(screen.getByLabelText(/^Floor/), "0");
    expect(screen.getByLabelText(/^Site/)).toHaveProperty("value", "");
    expect(screen.getByText("Enter it again: a changed input is sent whole, and this form can't show the original's value.")).toBeTruthy();
  });

  it("refuses the marker typed as JSON", async () => {
    show();
    const user = userEvent.setup();
    await site();
    await user.click(screen.getByRole("button", { name: "Edit as JSON" }));
    const text = screen.getByLabelText("The input, as JSON");
    await user.clear(text);
    await user.type(text, '{{"site": "HQ", "token": "[[redacted]"}');
    await user.click(screen.getByRole("button", { name: "Re-run live" }));
    expect(screen.getByText("It holds [redacted], a protected value the original kept: enter that value again.")).toBeTruthy();
    expect(reruns).toEqual([]);
  });

  it("says when the original input isn't kept, and starts from empty fields", async () => {
    input = { input: null, read_back: "absent", seeds: null };
    show();
    expect(await screen.findByText("Run 4a2b17e0's input isn't kept, so it can't be sent again. Fill in the fields to run it again.")).toBeTruthy();
    expect(await site()).toHaveProperty("value", "");
    await userEvent.type(await site(), "HQ");
    await userEvent.type(screen.getByLabelText(/^API token/), "t");
    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
    expect(reruns.map((r) => r.body)).toEqual([{ input: { site: "HQ", token: "t" }, mode: "live", expected_version_id: "v12" }]);
  });

  it("says when the original input can't be read back, and re-runs with new input", async () => {
    input = { input: null, read_back: "unreadable", seeds: null };
    show();
    expect(
      await screen.findByText(
        "Run 4a2b17e0's input can't be read back: it doesn't open, or the tenant's key is gone during an erasure. Fill in the fields to run it again.",
      ),
    ).toBeTruthy();
    expect(await site()).toHaveProperty("value", "");
  });

  it("turns to empty fields when the original input is gone by the time it's sent", async () => {
    rerunAnswers = [() => json({ error: "input_not_retained", messages: ["…"] }, 410)];
    show();
    await site();
    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
    expect(await screen.findByText("Run 4a2b17e0's input isn't kept, so it can't be sent again. Fill in the fields to run it again.")).toBeTruthy();
    expect(await site()).toHaveProperty("value", "");
  });
});

describe("re-running a CSV run (the run form design §5.4; the Rerun board)", () => {
  beforeEach(() => {
    form = CSV_FORM;
    input = CSV_KEPT;
  });

  it("re-runs its same rows, sending neither input nor file, its other fields shown read only", async () => {
    show(CSV_RUN, 7);
    const same = await screen.findByRole("radio", { name: "The same rows: 2,431 rows, as run 77e0b9d2 read them" });
    expect(same).toHaveProperty("checked", true);
    expect(screen.getByText("EMEA")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: /^Region/ })).toBeNull();
    expect(screen.getByText("Kept from the original run")).toBeTruthy();
    expect(screen.getByText("To change them, choose another file.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit as JSON" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Re-run live · 2,431 rows" }));
    expect(reruns.map((r) => r.body)).toEqual([{ mode: "live", expected_version_id: "v7" }]);
  });

  it("re-runs another file, checked as for a new start, its other fields sent whole, protected ones entered again", async () => {
    show(CSV_RUN, 7);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "Another file: it's checked here before the re-run starts, as for a new start" }));
    expect(screen.getByLabelText(/^Region/)).toHaveProperty("value", "EMEA");
    expect(screen.getByLabelText(/^API token/)).toHaveProperty("value", "");
    await user.upload(screen.getByLabelText("Choose a file"), new File(["Site name\nLyon\n"], "more.csv", { type: "text/csv" }));
    await user.type(screen.getByLabelText(/^API token/), "t");
    await user.click(await screen.findByRole("button", { name: "Re-run live · 12 rows" }));
    expect(reruns.map((r) => r.body)).toEqual([
      { input: { region: "EMEA", token: "t" }, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: { name: "Site name" } } },
    ]);
  });

  it("offers only another file once the run's input isn't kept", async () => {
    input = { input: null, read_back: "absent", seeds: null };
    show(CSV_RUN, 7);
    expect(await screen.findByLabelText("Choose a file")).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /^The same rows/ })).toBeNull();
    expect(screen.getByText("Run 77e0b9d2's input isn't kept, so it can't be sent again. Fill in the fields to run it again.")).toBeTruthy();
  });

  it("offers only another file when the run had no rows and the version reads a CSV", async () => {
    show({ ...CSV_RUN, csv: null }, 6);
    expect(await screen.findByLabelText("Choose a file")).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /^The same rows/ })).toBeNull();
  });

  it("starts from empty fields when the run had rows and the version reads no CSV, saying why", async () => {
    form = FORM;
    show(CSV_RUN, 7);
    expect(await screen.findByText("Version 12 doesn't read a CSV file: fill in its fields.")).toBeTruthy();
    expect(await site()).toHaveProperty("value", "");
    expect(screen.getByLabelText(/^API token/)).toHaveProperty("value", "");
  });
});
