// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Iterations } from "./Iterations";

const PATH = "/api/v1/t/t1/workflows/w1/draft/simulations/r1/steps";
const TOTAL = 12;
// Iteration n: is_offline took "true" on every other one; notify ran there (the 4th failed), and was skipped elsewhere.
const instance = (step: string, n: number) =>
  step === "id-is_offline"
    ? { step_id: step, key: "is_offline", iteration_key: `each_ap:${n}`, attempt: 1, status: "succeeded", effect: { port: n % 2 ? "true" : "false" } }
    : { step_id: step, key: "notify", iteration_key: `each_ap:${n}`, attempt: 1, status: n % 2 ? (n === 3 ? "failed" : "succeeded") : "skipped",
        error: n === 3 ? { code: "invalid_blocks", message: "Block 2 has no text." } : null };  // prettier-ignore

let asked: string[];
let failing: boolean;
let held: Promise<void> | null; // the next page's answer waits for it
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  asked = [];
  failing = false;
  held = null;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL((input as Request).url);
    asked.push(url.pathname + url.search);
    const m = url.pathname.match(/\/steps\/([^/]+)\/instances$/);
    if (failing || !m) return Promise.resolve(json({ error: "http_error" }, 500));
    const offset = Number(url.searchParams.get("offset"));
    const limit = Number(url.searchParams.get("limit"));
    if (offset > 0 && held) await held;
    const items = Array.from({ length: Math.max(0, Math.min(limit, TOTAL - offset)) }, (_, i) => instance(m[1]!, offset + i));
    return Promise.resolve(json({ total: TOTAL, items }));
  });
});
afterEach(() => vi.restoreAllMocks());

function show() {
  const onOpen = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Iterations
        tenantId="t1" workflowId="w1" requestId="r1" loop={{ key: "each_ap", prefix: "" }}
        body={[{ id: "id-is_offline", key: "is_offline", type: "flow.if@1" }, { id: "id-notify", key: "notify", type: "slack.post@1" }]}
        onOpen={onOpen}
      />
    </QueryClientProvider>,
  );  // prettier-ignore
  return { onOpen };
}
const rows = (list: HTMLElement) => within(list).getAllByRole("listitem").map((li) => li.textContent);

describe("a loop's iterations, paged (§7.5; the ResultPanel board)", () => {
  it("shows four iterations at a time, each as what its steps did, from the server's pages", async () => {
    show();
    const list = await screen.findByRole("list", { name: "each_ap's iterations, 1 to 4 of 12" });
    expect(rows(list).slice(0, 3)).toEqual(["1 · is_offline → false · notify skipped", "2 · is_offline → true · notify succeeded", "3 · is_offline → false · notify skipped"]);
    expect(rows(list)[3]).toContain("4 · is_offline → true · notify failed · invalid_blocks");
    expect(screen.getByText("Iterations 1–4 of 12")).toBeTruthy();
    expect(asked).toContain(`${PATH}/id-notify/instances?offset=0&limit=4`);
  });

  it("opens a failed step's instance in its iteration", async () => {
    const { onOpen } = show();
    await userEvent.click(await screen.findByRole("button", { name: "Open notify, iteration 4" }));
    expect(onOpen).toHaveBeenCalledWith("id-notify", "each_ap:3");
  });

  it("pages on, and back, and stops at the last", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Next 4" }));
    expect(await screen.findByRole("list", { name: "each_ap's iterations, 5 to 8 of 12" })).toBeTruthy();
    expect(asked).toContain(`${PATH}/id-is_offline/instances?offset=4&limit=4`);
    await userEvent.click(screen.getByRole("button", { name: "Next 4" }));
    expect(await screen.findByText("Iterations 9–12 of 12")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Next/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Previous 4" }));
    expect(await screen.findByText("Iterations 5–8 of 12")).toBeTruthy();
  });

  it("keeps the page shown and the focus where it was while the next one is read (the review's 2)", async () => {
    let answer!: () => void;
    held = new Promise((resolve) => (answer = resolve));
    show();
    const next = await screen.findByRole("button", { name: "Next 4" });
    await userEvent.click(next);
    expect(screen.getByRole("list", { name: "each_ap's iterations, 1 to 4 of 12" })).toBeTruthy(); // not "Reading…"
    expect(document.activeElement).toBe(next);
    answer();
    expect(await screen.findByRole("list", { name: "each_ap's iterations, 5 to 8 of 12" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Next 4" }));
  });

  it("gives the focus to Previous when the last page has no Next, and to Next when the first has no Previous", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Next 4" }));
    await screen.findByText("Iterations 5–8 of 12");
    await userEvent.click(screen.getByRole("button", { name: "Next 4" }));
    await screen.findByText("Iterations 9–12 of 12");
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Previous 4" })));
    await userEvent.click(screen.getByRole("button", { name: "Previous 4" }));
    await userEvent.click(await screen.findByRole("button", { name: "Previous 4" }));
    await screen.findByText("Iterations 1–4 of 12");
    await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Next 4" })));
  });

  it("says when they couldn't be read, and reads them again", async () => {
    failing = true;
    show();
    expect(await screen.findByText("The iterations couldn't be read.")).toBeTruthy();
    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "Read them again" }));
    expect(await screen.findByRole("list", { name: "each_ap's iterations, 1 to 4 of 12" })).toBeTruthy();
  });
});
