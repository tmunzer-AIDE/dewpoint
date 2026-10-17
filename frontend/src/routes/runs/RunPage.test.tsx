// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onAnnounce } from "../../lib/announce";
import type { Run, RunSteps } from "../../lib/runs";
import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, RUN_TYPES, local } from "../../test/runs";
import type { CanvasProps } from "../editor/Canvas";
import { RunPage } from "./RunPage";

// The canvas stands in as the editor's tests have it: React Flow isn't drawn in jsdom. It shows what it was given.
vi.mock("../editor/Canvas", async () => {
  const { useEffect } = await import("react");
  return {
    Canvas: (props: CanvasProps) => {
      useEffect(() => {
        if (props.focusRequest) document.querySelector<HTMLElement>(`[data-item="${props.focusRequest.id}"]`)?.focus();
      }, [props.focusRequest]);
      return (
        <div
          role="group"
          aria-label="Workflow steps"
          onKeyDown={props.onKeyDown}
          onFocus={(e) => {
            const id = (e.target as HTMLElement).dataset.item;
            if (id) props.onFocusItem(id);
          }}
          data-editable={String(props.editable)}
          data-current={props.current ?? ""}
          data-results-label={props.resultsLabel ?? ""}
          data-results={JSON.stringify((props.results ? [...props.results.entries()] : []).map(([k, tags]) => [k, tags.map((t) => t.text)]))}
          data-start-tags={(props.start.tags ?? []).map((t) => t.text).join(",")}
        >
          <button data-item="start" tabIndex={props.focusId === "start" ? 0 : -1} aria-label={props.start.label} onClick={props.start.onOpen}>
            {props.start.summary}
          </button>
          {(props.doc.nodes ?? []).map((n) => (
            <button key={n.id} data-item={`node:${n.id}`} tabIndex={props.focusId === `node:${n.id}` ? 0 : -1} onClick={() => props.onItem({ kind: "open", node: n.id })}>
              {n.key}
            </button>
          ))}
        </div>
      );
    },
  };
});

const RUN: Run = FAILED_RUN;
const NOW = Date.parse(local(10, 2, 19));
const VERSION = { id: "v2", number: 2, graph: FAILED_GRAPH, active: true, blocked_by: [], cel_profile: "p", engine_abi: 9, executable: true,
  expressions: [], graph_hash: "h", node_refs: [], published_at: local(8, 0, 0), published_by: null, version_hash: "vh" };  // prettier-ignore

let answers: Map<string, () => Response>;
let reads: string[];

beforeEach(() => {
  answers = new Map([
    ["/api/v1/node-types", json(RUN_TYPES)],
    ["/api/v1/t/t1/workflows/w1/versions/v2", json(VERSION)],
    [`/api/v1/t/t1/runs/${RUN.id}/steps`, json(FAILED_STEPS)],
  ]);
  reads = [];
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    reads.push(path);
    const answer = answers.get(path);
    return Promise.resolve(answer ? answer() : new Response(JSON.stringify({ error: "not_found" }), { status: 404 }));
  });
});
afterEach(() => vi.restoreAllMocks());

function json(body: unknown, status = 200) {
  return () => new Response(JSON.stringify(body), { status });
}

function show(runId = RUN.id) {
  const root = createRootRoute({ component: () => <RunPage tenantId="t1" runId={runId} /> });
  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs" });
  const editor = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId" });
  const router = createRouter({ routeTree: root.addChildren([runs, editor]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

it("names the run by its workflow and its short id, with the way back to Runs (§5.3)", async () => {
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
  const router = show();
  expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
  expect(screen.getByText("run 4a2b17e0")).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "← Runs" }));
  expect(router.state.location.pathname).toBe("/t/t1/runs");
});

it("says a run that isn't kept any more, or never was, is neither, with Back to Runs (§5.4; the RunOther board)", async () => {
  const router = show("0d4f9b2a-0000-4000-8000-000000000000");
  expect(await screen.findByRole("heading", { level: 1, name: "Run 0d4f9b2a" })).toBeTruthy();
  expect(screen.getByText("This run isn't kept any more, or it never existed here.")).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "Back to Runs" }));
  expect(router.state.location.pathname).toBe("/t/t1/runs");
});

it("says a run can't be read while its tenant is erased (§5.5)", async () => {
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json({ error: "key_unusable" }, 503));
  show();
  expect((await screen.findByRole("alert")).textContent).toBe("This run can't be read while the tenant is being erased.");
});

it("says the run couldn't be read, and reads it again when asked", async () => {
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json({ error: "internal_error" }, 500));
  show();
  expect((await screen.findByRole("alert")).textContent).toBe("The run couldn't be read.");
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
});

const canvas = () => screen.getByRole("group", { name: "Workflow steps" });
const bar = () => screen.getByRole("heading", { level: 1 }).parentElement!;

describe("a run's page (§5.3; the RunFailed board)", () => {
  it("shows a failed live run: its bar, the live banner, and each step's result on its version's canvas, read only", async () => {
    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
    const router = show();
    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
    expect(within(bar()).getByText("Failed").className).toContain("border-danger");
    expect(within(bar()).getByText("Live").className).toContain("text-live");
    expect(within(bar()).getByText(/^version 2 · webhook, Mist events · started/).textContent).toBe("version 2 · webhook, Mist events · started today 09:41:12 · 38 s");
    expect(screen.getByRole("note").textContent).toBe("Live run. It acted for real: steps marked sent called their connections.");
    expect(screen.getByText(/^Ended: failed at notify_noc/).textContent).toBe("Ended: failed at notify_noc · today 09:41:50");
    expect(canvas().dataset.editable).toBe("false");
    expect(canvas().dataset.resultsLabel).toBe("result");
    expect(JSON.parse(canvas().dataset.results!)).toEqual([
      ["id-get_device", ["succeeded", "sent", "0.4 s"]],
      ["id-is_down", ["succeeded", "→ true"]],
      ["id-open_case", ["succeeded", "sent", "1.8 s"]],
      ["id-notify_noc", ["failed", "attempt 3 of 3", "channel_not_found"]],
      ["id-log_recovery", ["skipped"]],
    ]);
    expect(canvas().dataset.startTags).toBe("input");
    expect(screen.getByRole("button", { name: "Start: webhook, Mist events. Open the run's start" })).toBeTruthy();
    await userEvent.click(screen.getByRole("link", { name: "Open the workflow" }));
    expect(router.state.location.pathname).toBe("/t/t1/workflows/w1");
  });

  it("copies the run's whole id, and says so", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Copy id" }));
    expect(writeText).toHaveBeenCalledWith(RUN.id);
    await vi.waitFor(() => expect(said).toEqual(["Copied the run's id"]));
    stop();
  });

  it("says when the browser refuses to copy the id", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) }, configurable: true });
    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Copy id" }));
    await vi.waitFor(() => expect(said).toEqual(["The run's id couldn't be copied"]));
    stop();
  });

  it("walks the read-only canvas with the arrow keys (D16)", async () => {
    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
    show();
    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
    within(canvas()).getByRole("button", { name: "Start: webhook, Mist events. Open the run's start" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement?.textContent).toBe("get_device");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(document.activeElement?.textContent).toBe("open_case");
  });

  it("says a draft simulation is one, names its revision, reads the draft it ran and opens in the editor (the RunOther board)", async () => {
    const draft: Run = { ...RUN, status: "succeeded", mode: "simulate", version_id: null, draft_snapshot_id: "s1", draft_revision: 14, error: null,
      started_by: "nadia@example.com", trigger: { source: "manual", schedule: null, endpoint: null, rerun_of: null } };  // prettier-ignore
    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(draft));
    answers.set("/api/v1/t/t1/workflows/w1/draft/snapshots/s1", json({ id: "s1", revision: 14, graph: FAILED_GRAPH }));
    show();
    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
    expect(within(bar()).getByText("Draft simulation").className).toContain("hatch-sim");
    expect(within(bar()).getByText(/^draft revision 14/).textContent).toBe("draft revision 14 · by hand, nadia@example.com · started today 09:41:12 · 38 s");
    expect(screen.getByText(/^Simulated\./).closest("[class*=hatch-sim]")!.textContent).toBe("Simulated. Nothing was sent. The draft's revision 14 ran, not a published version.");
    expect(screen.getByRole("link", { name: "Open in the editor" })).toBeTruthy();
    expect(reads).not.toContain("/api/v1/t/t1/workflows/w1/versions/v2");
  });
});

describe("reading a run while it runs (§5.3)", () => {
  // Timers the test moves on, and real time besides, so the page's own waits still pass.
  beforeEach(() => void vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"], shouldAdvanceTime: true }));
  afterEach(() => void vi.useRealTimers());

  const running: Run = { ...RUN, status: "running", ended_at: null, error: null };
  const runningSteps: RunSteps = { ...FAILED_STEPS, steps: FAILED_STEPS.steps.slice(0, 3) };
  const count = (path: string) => reads.filter((r) => r === path).length;
  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
  const STEPS_PATH = `${RUN_PATH}/steps`;

  it("says a live run acts for real while it runs, and how long so far", async () => {
    answers.set(RUN_PATH, json(running));
    show();
    await vi.waitFor(() => expect(screen.getByRole("note").textContent).toBe("Live run. It acts for real: steps marked sent called their connections."));
    expect(within(bar()).getByText(/^version 2/).textContent).toBe("version 2 · webhook, Mist events · started today 09:41:12 · 21 min 7 s so far");
  });

  it("reads it every second at first, backing off; its steps at most every 5 s", async () => {
    answers.set(RUN_PATH, json(running));
    answers.set(STEPS_PATH, json(runningSteps));
    show();
    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(count(RUN_PATH)).toBe(2);
    expect(count(STEPS_PATH)).toBe(1);
    await act(() => vi.advanceTimersByTimeAsync(4000));
    expect(count(RUN_PATH)).toBe(3); // at 0, 1 and 3 s: a second, then two, then three… (as a simulation, pollEvery)
    expect(count(STEPS_PATH)).toBe(2);
  });

  it("keeps the run when a read fails while it runs, says as of when, and tries again", async () => {
    answers.set(RUN_PATH, json(running));
    answers.set(STEPS_PATH, json(runningSteps));
    show();
    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
    answers.set(RUN_PATH, json({ error: "internal_error" }, 500));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(await screen.findByText("Couldn't be refreshed · as of 10:02:19")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "AP offline triage" })).toBeTruthy();
    expect(canvas().dataset.results).not.toBe("[]");
    answers.set(RUN_PATH, json(running));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(screen.queryByText(/^Couldn't be refreshed/)).toBeNull());
  });

  it("says when it ends, reads its steps then and once more 5 s later, and then no more", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    answers.set(RUN_PATH, json(running));
    answers.set(STEPS_PATH, json(runningSteps));
    show();
    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
    answers.set(RUN_PATH, json(RUN));
    answers.set(STEPS_PATH, json(FAILED_STEPS));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    await vi.waitFor(() => expect(said).toEqual(["Run ended: failed"]));
    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(2));
    const [run, steps] = [count(RUN_PATH), count(STEPS_PATH)];
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect([count(RUN_PATH), count(STEPS_PATH)]).toEqual([run + 1, steps + 1]);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect([count(RUN_PATH), count(STEPS_PATH)]).toEqual([run + 1, steps + 1]);
    expect(said).toEqual(["Run ended: failed"]);
    stop();
  });
});
