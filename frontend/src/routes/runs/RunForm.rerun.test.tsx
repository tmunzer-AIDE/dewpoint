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

let input: unknown;
let reruns: { key: string | null; body: unknown }[];
let rerunAnswers: (() => Response)[];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  input = KEPT;
  reruns = [];
  rerunAnswers = [];
  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (req) => {
    const request = req as Request;
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(FORM);
    if (path === `/api/v1/t/t1/runs/${RUN.id}/input`) return json(input);
    if (request.method === "POST" && path === `/api/v1/t/t1/runs/${RUN.id}/rerun`) {
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
