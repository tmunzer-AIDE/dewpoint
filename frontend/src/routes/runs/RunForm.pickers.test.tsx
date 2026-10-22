// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StartForm } from "../../lib/runForm";
import type { Run } from "../../lib/runs";
import { FAILED_RUN, local } from "../../test/runs";
import { RunForm } from "./RunForm";

// The Main board's form: a site picked from Acme Prod's sites (a made-up service, D24), and a change ticket.
const C1 = "00000000-0000-4000-8000-0000000000c1";
const LYON = "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d";
const SITE = {
  name: "site_id", title: "Site ID", type: "string", required: true, sensitive: false,
  picker: { node: "acme.sites.get@1", field: "site_id", connection: C1, list: { plugin: "Acme", title: "Org sites", noun: "sites" } },
};  // prettier-ignore
const FORM: StartForm = {
  workflow_id: "w1", version_id: "v7", version_number: 7, published_at: local(9, 12, 0), published_by: null, csv: null,
  fields: [SITE, { name: "ticket", title: "Change ticket", type: "string", required: false, sensitive: false }],
};  // prettier-ignore
const NEWER: StartForm = { ...FORM, version_id: "v8", version_number: 8 };
const CSV_FORM: StartForm = {
  ...FORM, csv: { max_rows: 10_000, max_bytes: 5 * 1024 * 1024, columns: [{ header: "Site name", name: "name", type: "string", required: true, sensitive: false }] },
};  // prettier-ignore
const UPLOADED = {
  version_id: "v7", upload_id: "u1", expires_at: local(11, 0, 0), headers: ["Site name"], row_count: 12, mapping: { name: "Site name" },
  default_mapping: { status: "none" }, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0, error_groups: [], rows_with_errors: 0,
};  // prettier-ignore
const SITES = [{ value: LYON, label: "Lyon DC" }, { value: "1b6e93f2-0000-4000-8000-000000000002", label: "Lyon store 4" }];
const RUN: Run = { ...FAILED_RUN, version_id: "v7" };
const NAMED = { input: { site_id: LYON, ticket: "CHG-1042" }, names: { site_id: "Lyon DC" }, read_back: "kept", seeds: null };

let forms: StartForm[];
let input: unknown;
let listings: unknown[];
let posts: { key: string | null; body: unknown }[];
let answers: (() => Promise<Response>)[];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  forms = [FORM];
  input = NAMED;
  listings = [];
  posts = [];
  answers = [];
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (req) => {
    const request = req as Request;
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(forms.length > 1 ? forms.shift() : forms[0]);
    if (path === "/api/v1/t/t1/connections") return json([{ id: C1, name: "Acme Prod", type: "acme", status: "ok", revision: 1, config: {}, secret_set: true }]);
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/input-options") {
      listings.push(JSON.parse(await request.text()));
      return json({ options: SITES });
    }
    if (path.endsWith("/input")) return json(input);
    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads") return json(UPLOADED, 201);
    if (request.method === "POST" && (path === "/api/v1/t/t1/workflows/w1/runs" || path.endsWith("/rerun"))) {
      posts.push({ key: request.headers.get("Idempotency-Key"), body: JSON.parse(await request.text()) as unknown });
      return (answers.shift() ?? (() => Promise.resolve(json({ id: "r1" }, 202))))();
    }
    return json({ error: "not_found" }, 404);
  });
});
afterEach(() => vi.restoreAllMocks());

function show(rerun?: { run: Run; ranVersion: number | null }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <RunForm tenantId="t1" workflow={{ id: "w1", name: "Site onboarding" }} rerun={rerun} onStarted={vi.fn()} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}
const site = () => screen.findByRole("combobox", { name: /^Site ID/ });
async function pick(label = "Lyon DC") {
  await userEvent.click(await screen.findByRole("button", { name: "Show choices: Site ID" }));
  await userEvent.click(await screen.findByRole("option", { name: new RegExp(`^${label}`) }));
}
const NAME = { site_id: { value: LYON, label: "Lyon DC" } };

describe("a picker in the run form (the 4f-3 design §5.3, §5.5)", () => {
  it("lists the choices of the version the form shows", async () => {
    show();
    await userEvent.type(await site(), "ly{Enter}");
    await screen.findByRole("listbox", { name: "Choices for Site ID" });
    expect(listings).toEqual([{ field: "site_id", query: "ly", expected_version_id: "v7" }]);
  });

  it("starts with the pick's name beside the input, never in the key: the same form sent again goes under the same key", async () => {
    answers = [() => Promise.reject(new TypeError("Failed to fetch"))]; // the answer lost on the way
    show();
    await pick();
    await userEvent.click(screen.getByRole("button", { name: "Start the live run" }));
    await screen.findByText(/The server didn't answer/);
    expect(posts[0]!.body).toEqual({ input: { site_id: LYON }, mode: "live", expected_version_id: "v7", names: NAME });
    await userEvent.type(await site(), "x{Backspace}"); // the same value, typed over: its name goes
    await userEvent.click(screen.getByRole("button", { name: "Start the live run" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual({ key: posts[0]!.key, body: { input: { site_id: LYON }, mode: "live", expected_version_id: "v7" } });
  });

  it("sends a name with the input entered as JSON only while it holds the picked value", async () => {
    answers = [() => Promise.reject(new TypeError("Failed to fetch"))];
    show();
    await pick();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit as JSON" }));
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.body).toEqual({ input: { site_id: LYON }, mode: "live", expected_version_id: "v7", names: NAME });
    await user.clear(screen.getByLabelText("The input, as JSON"));
    await user.click(screen.getByLabelText("The input, as JSON"));
    await user.paste('{"site_id": "s9"}');
    await user.click(screen.getByRole("button", { name: "Start the live run" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]!.body).toEqual({ input: { site_id: "s9" }, mode: "live", expected_version_id: "v7" });
  });

  it("reads a newer version after a refused start, keeping the values that fit but no name, and lists for that version", async () => {
    forms = [FORM, NEWER];
    const changed = { error: "version_changed", messages: ["Version 8 is the active version now."], active_version_id: "v8", active_version_number: 8 };
    answers = [() => Promise.resolve(json(changed, 409))];
    show();
    await pick();
    await userEvent.click(screen.getByRole("button", { name: "Start the live run" }));
    await screen.findByText(/^Version 8 was published while this was open/);
    expect(await site()).toHaveProperty("value", LYON);
    expect(screen.getByText("One of Acme Prod's sites: type part of its name, then Show choices.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Start the live run" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]!.body).toEqual({ input: { site_id: LYON }, mode: "live", expected_version_id: "v8" });
    await userEvent.click(screen.getByRole("button", { name: "Show choices: Site ID" }));
    await waitFor(() => expect(listings.at(-1)).toEqual({ field: "site_id", query: LYON, expected_version_id: "v8" }));
  });

  it("says a simulated start's listing reads the connection now, changing nothing in Mist", async () => {
    show();
    await userEvent.click(await screen.findByRole("radio", { name: "Simulated" }));
    await userEvent.click(screen.getByRole("button", { name: "Show choices: Site ID" }));
    await screen.findByRole("listbox");
    expect(screen.getByText("Read from Acme Prod now: listing changes nothing in Mist.")).toBeTruthy();
  });

  it("lists and names a picker beside a CSV file, the same for every row (the MoreStates board)", async () => {
    forms = [CSV_FORM];
    show();
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText("Choose a file"), new File(["Site name\nLyon\n"], "sites.csv", { type: "text/csv" }));
    await pick();
    await user.click(await screen.findByRole("button", { name: "Start the live run · 12 rows" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.body).toEqual({
      input: { site_id: LYON }, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: { name: "Site name" } }, names: NAME,
    });  // prettier-ignore
  });
});

describe("a picker in a re-run (the 4f-3 design §5.5)", () => {
  it("names the first run's value as picked then; untouched, the re-run sends neither input nor names", async () => {
    show({ run: RUN, ranVersion: 7 });
    expect(await screen.findByText("Lyon DC, as picked for the first run.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.body).toEqual({ mode: "live", expected_version_id: "v7" });
  });

  it("sends the first run's name with a changed input while it holds that value", async () => {
    show({ run: RUN, ranVersion: 7 });
    await screen.findByText("Lyon DC, as picked for the first run.");
    await userEvent.type(screen.getByRole("textbox", { name: /^Change ticket/ }), "-2");
    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]!.body).toEqual({ input: { site_id: LYON, ticket: "CHG-1042-2" }, mode: "live", expected_version_id: "v7", names: NAME });
  });

  it("names nothing for a value the first run's names don't hold", async () => {
    input = { ...NAMED, names: {} };
    show({ run: RUN, ranVersion: 7 });
    expect(await screen.findByText("One of Acme Prod's sites: type part of its name, then Show choices.")).toBeTruthy();
    expect(await site()).toHaveProperty("value", LYON);
  });
});
