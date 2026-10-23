// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onAnnounce } from "../../lib/announce";
import type { Run, RunSteps } from "../../lib/runs";
import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, LOOP_GRAPH, LOOP_STEPS, LOOP_TOTAL, RUN_TYPES, attempt, local, loopInstance } from "../../test/runs";
import type { CanvasProps } from "../editor/Canvas";
import { landOn } from "./landing";
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

let answers: Map<string, (url: URL) => Response>;
let reads: string[];
let role: string;

beforeEach(() => {
  role = "operator";
  answers = new Map([
    ["/api/v1/t/t1", () => json({ id: "t1", name: "Acme Retail", slug: "acme-retail", require_passkey: false, role })()],
    ["/api/v1/node-types", json(RUN_TYPES)],
    ["/api/v1/t/t1/workflows/w1/versions/v2", json(VERSION)],
    [`/api/v1/t/t1/runs/${RUN.id}/steps`, json(FAILED_STEPS)],
  ]);
  reads = [];
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = new URL((input as Request).url);
    reads.push(url.pathname);
    const answer = answers.get(url.pathname);
    return Promise.resolve(answer ? answer(url) : new Response(JSON.stringify({ error: "not_found" }), { status: 404 }));
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

it("focuses its name when a start landed on it, once it's read (the run form design §5.2)", async () => {
  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
  landOn(RUN.id);
  show();
  const heading = await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
  await vi.waitFor(() => expect(document.activeElement).toBe(heading));
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

describe("its steps unread", () => {
  it("says when a run's steps couldn't be read, and reads them again when asked", async () => {
    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
    answers.set(`/api/v1/t/t1/runs/${RUN.id}/steps`, json({ error: "internal_error" }, 500));
    show();
    expect((await screen.findByText("Its steps' results couldn't be read.")).getAttribute("role")).toBe("alert");
    answers.set(`/api/v1/t/t1/runs/${RUN.id}/steps`, json(FAILED_STEPS));
    await userEvent.click(screen.getByRole("button", { name: "Read them again" }));
    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
    expect(screen.queryByText("Its steps' results couldn't be read.")).toBeNull();
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

  it("reads an open drawer's attempts with the summary while the run runs", async () => {
    const ATTEMPTS = `${RUN_PATH}/steps/id-get_device/attempts`;
    answers.set(RUN_PATH, json(running));
    answers.set(STEPS_PATH, json(runningSteps));
    answers.set(ATTEMPTS, json({ items: [runningSteps.steps[0]!.final] }));
    show();
    await vi.waitFor(() => expect(count(STEPS_PATH)).toBe(1));
    await userEvent.click(within(canvas()).getByRole("button", { name: "get_device" }));
    await vi.waitFor(() => expect(count(ATTEMPTS)).toBe(1));
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(count(ATTEMPTS)).toBe(2);
  });
});

describe("a step's result in the drawer (§5.3; the RunFailed and RunLoop boards)", () => {
  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
  const attemptsOf = (key: string) => `${RUN_PATH}/steps/id-${key}/attempts`;
  const drawer = (key: string) => screen.getByRole("complementary", { name: key });
  const failedAttempt = (n: number, at: number) =>
    attempt("notify_noc", { attempt: n, status: "failed", started_at: local(9, 41, at), ended_at: local(9, 41, at + 1, 200 - n * 100),
      error: { code: "channel_not_found", message: "The channel wasn't found." } });  // prettier-ignore

  beforeEach(() => {
    answers.set(RUN_PATH, json(RUN));
    answers.set(attemptsOf("notify_noc"), json({ items: [failedAttempt(1, 20), failedAttempt(2, 31), { ...FAILED_STEPS.steps[3]!.final, started_at: local(9, 41, 49) }] }));
    answers.set(attemptsOf("get_device"), json({ items: [attempt("get_device", { output: { name: "Paris-Opera-12", status: "disconnected" } })] }));
  });

  it("opens a failed run on its failed step: its status and times, its error, its attempts, its input with its marks", async () => {
    show();
    const side = await screen.findByRole("complementary", { name: "notify_noc" });
    await vi.waitFor(() => expect(document.activeElement).toBe(within(side).getByRole("heading", { name: "notify_noc" })));
    expect(canvas().dataset.current).toBe("id-notify_noc");
    expect(within(side).getByRole("tab", { name: "Result", selected: true })).toBeTruthy();
    expect(within(side).getByText("Failed").className).toContain("border-danger");
    expect(await within(side).findByText("attempt 3 of 3 · 09:41:20 to 09:41:50 · 30 s")).toBeTruthy();
    expect(within(side).getAllByText("channel_not_found")[0]!.closest("p")!.textContent).toBe("channel_not_found · The channel wasn't found.");
    const attempts = within(within(side).getByRole("region", { name: "Attempts" })).getAllByRole("listitem");
    expect(attempts.map((a) => a.textContent)).toEqual([
      "1failedchannel_not_found09:41:201.1 s", "2failedchannel_not_found09:41:311.0 s", "3failedchannel_not_found09:41:491.0 s",
    ]);  // prettier-ignore
    const input = within(side).getByRole("region", { name: "Input" });
    expect(within(input).getByText("As the last attempt received it. Sensitive values are redacted and long ones cut.")).toBeTruthy();
    expect(within(input).getAllByRole("term").map((k) => k.textContent)).toEqual(["channel", "text", "token", "blocks"]);
    expect(within(input).getAllByRole("definition").map((v) => v.textContent)).toEqual([
      '"#noc-alert"', '"AP Paris-Opera-12 offline since 09:38"', "redacted", "truncated",
    ]);  // prettier-ignore
    expect(within(within(side).getByRole("region", { name: "Output" })).getByText("None: the step failed.")).toBeTruthy();
  });

  it("shows a value whatever its words, even an object's own property names", async () => {
    const steps = structuredClone(FAILED_STEPS);
    steps.steps[3]!.final!.input = { a: "__proto__", b: "constructor", c: "[redacted]" };
    answers.set(`${RUN_PATH}/steps`, json(steps));
    answers.set(attemptsOf("notify_noc"), json({ items: [steps.steps[3]!.final] }));
    show();
    const input = await within(await screen.findByRole("complementary", { name: "notify_noc" })).findByRole("region", { name: "Input" });
    await vi.waitFor(() => expect(within(input).getAllByRole("definition").map((d) => d.textContent)).toEqual(['"__proto__"', '"constructor"', "redacted"]));
  });

  it("opens a step from the canvas, its setup read only on Setup, and gives focus back to its card on Close", async () => {
    show();
    await screen.findByRole("complementary", { name: "notify_noc" });
    await userEvent.click(within(canvas()).getByRole("button", { name: "get_device" }));
    const side = drawer("get_device");
    expect(await within(side).findByText("attempt 1 of 3 · 09:41:13 · 0.4 s")).toBeTruthy();
    expect(within(within(side).getByRole("region", { name: "Output" })).getAllByRole("definition").map((v) => v.textContent)).toEqual(['"Paris-Opera-12"', '"disconnected"']);
    await userEvent.click(within(side).getByRole("tab", { name: "Setup" }));
    expect(within(side).getByText("This step has nothing to set up.")).toBeTruthy();
    await userEvent.click(within(side).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("complementary")).toBeNull();
    await vi.waitFor(() => expect(document.activeElement?.textContent).toBe("get_device"));
  });

  it("links the run a step started, with its workflow and status (the RunLoop board)", async () => {
    const child = { ...RUN, id: "7d2e0c11-0000-4000-8000-000000000000", workflow_name: "Escalate an outage", status: "succeeded", error: null };
    const steps = structuredClone(FAILED_STEPS);
    steps.steps[2]!.final!.child_run_id = child.id;
    answers.set(`${RUN_PATH}/steps`, json(steps));
    answers.set(`/api/v1/t/t1/runs/${child.id}`, json(child));
    answers.set(attemptsOf("open_case"), json({ items: [steps.steps[2]!.final] }));
    const router = show();
    await screen.findByRole("complementary", { name: "notify_noc" });
    await userEvent.click(within(canvas()).getByRole("button", { name: "open_case" }));
    const link = await within(drawer("open_case")).findByRole("link", { name: "7d2e0c11" });
    expect(link.closest("p")!.textContent).toBe("Its run: 7d2e0c11 · Escalate an outage · Succeeded");
    await userEvent.click(link);
    expect(router.state.location.pathname).toBe(`/t/t1/runs/${child.id}`);
  });

  it("shows the result of a step whose type the server no longer knows, and says why its settings can't be shown", async () => {
    const gone = "acme.gone@1";
    const graph = { ...FAILED_GRAPH, nodes: FAILED_GRAPH.nodes!.map((n) => (n.key === "get_device" ? { ...n, type: gone } : n)) };
    const steps = { ...FAILED_STEPS, steps: FAILED_STEPS.steps.map((s) => (s.key === "get_device" ? { ...s, type: gone } : s)) };
    answers.set("/api/v1/t/t1/workflows/w1/versions/v2", json({ ...VERSION, graph }));
    answers.set(`${RUN_PATH}/steps`, json(steps));
    show();
    await screen.findByRole("complementary", { name: "notify_noc" });
    await userEvent.click(within(canvas()).getByRole("button", { name: "get_device" }));
    const side = drawer("get_device");
    expect(await within(side).findByText("attempt 1 · 09:41:13 · 0.4 s")).toBeTruthy();
    await userEvent.click(within(side).getByRole("tab", { name: "Setup" }));
    expect(within(side).getByText("This server doesn't know this step's type, so its settings can't be shown. They're kept as they are.")).toBeTruthy();
  });
});

describe("a loop (§5.3; the RunLoop board)", () => {
  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
  const loopRun: Run = { ...RUN, status: "succeeded", error: null, ended_at: local(14, 4, 31) };
  const instances = (key: "is_offline" | "notify") => (url: URL) => {
    const [offset, limit, within] = [Number(url.searchParams.get("offset")), Number(url.searchParams.get("limit")), url.searchParams.get("within")];
    const all = Array.from({ length: LOOP_TOTAL }, (_, n) => loopInstance(key, n)).filter((i) => !within || i.iteration_key === within);
    return new Response(JSON.stringify({ total: all.length, items: all.slice(offset, offset + limit) }));
  };
  const drawer = (key: string) => screen.getByRole("complementary", { name: key });

  beforeEach(() => {
    answers.set(RUN_PATH, json(loopRun));
    answers.set(`${RUN_PATH}/steps`, json(LOOP_STEPS));
    answers.set("/api/v1/t/t1/workflows/w1/versions/v2", json({ ...VERSION, graph: LOOP_GRAPH }));
    answers.set(`${RUN_PATH}/steps/id-is_offline/instances`, instances("is_offline"));
    answers.set(`${RUN_PATH}/steps/id-notify/instances`, instances("notify"));
    answers.set(`${RUN_PATH}/steps/id-notify/attempts`, (url) => json({ items: [loopInstance("notify", Number(url.searchParams.get("iteration")!.split(":")[1]))] })());
    answers.set(`${RUN_PATH}/steps/id-each_ap/attempts`, json({ items: [LOOP_STEPS.steps[1]!.final] }));
  });

  it("totals each step on the canvas, from the server's summary", async () => {
    show();
    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
    expect((JSON.parse(canvas().dataset.results!) as unknown[]).slice(1)).toEqual([
      ["id-each_ap", ["succeeded", "120 iterations"]],
      ["id-is_offline", ["120 instances: 120 succeeded", "→ true ×17", "→ false ×103"]],
      ["id-notify", ["120 instances: 14 succeeded · 3 failed · 103 skipped", "sent"]],
    ]);  // prettier-ignore
  });

  it("pages the loop's iterations four at a time, and opens a failed one's step at that iteration", async () => {
    show();
    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
    await userEvent.click(within(canvas()).getByRole("button", { name: "each_ap" }));
    const side = drawer("each_ap");
    expect(await within(side).findByText("120 iterations · 14:02:10 to 14:04:30 · 2 min 20 s")).toBeTruthy();
    const list = await within(side).findByRole("list", { name: "each_ap's iterations, 1 to 4 of 120" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "1 · is_offline → false · notify skipped", "2 · is_offline → true · notify succeeded", "3 · is_offline → false · notify skipped",
      "4 · is_offline → true · notify failed · invalid_blocks Open",
    ]);  // prettier-ignore
    await userEvent.click(within(side).getByRole("button", { name: "Next 4" }));
    expect(await within(side).findByRole("list", { name: "each_ap's iterations, 5 to 8 of 120" })).toBeTruthy();
    await userEvent.click(within(side).getByRole("button", { name: "Previous 4" }));
    await userEvent.click(await within(side).findByRole("button", { name: "Open notify, iteration 4" }));
    const step = drawer("notify");
    expect(await within(step).findByText("iteration 4 · attempt 1 of 3 · 14:02:13 · 0.9 s")).toBeTruthy();
    expect(within(step).getAllByText("invalid_blocks")[0]!.closest("p")!.textContent).toBe("invalid_blocks · Slack refused the message's blocks.");
    expect(within(step).getByRole<HTMLSelectElement>("combobox", { name: "Iteration" }).value).toBe("each_ap:3");
  });

  it("shows one of a loop step's first 50 iterations at a time, picked (§5.3; 4d-1c's picker)", async () => {
    show();
    await vi.waitFor(() => expect(canvas().dataset.results).not.toBe("[]"));
    await userEvent.click(within(canvas()).getByRole("button", { name: "notify" }));
    const side = drawer("notify");
    expect(within(side).getByText("120 instances: 14 succeeded · 3 failed · 103 skipped")).toBeTruthy();
    const pick = await within(side).findByRole("combobox", { name: "Iteration" });
    expect(within(pick).getAllByRole("option")).toHaveLength(50);
    expect(within(side).getByText("The first 50 of 120 iterations. Open any other from each_ap's list.")).toBeTruthy();
    await userEvent.selectOptions(pick, "each_ap:1");
    await userEvent.click(within(side).getByRole("button", { name: "Show" }));
    expect(await within(side).findByText("iteration 2 · attempt 1 of 3 · 14:02:11 · 0.9 s")).toBeTruthy();
    expect(within(side).getByText("Succeeded").className).toContain("border-ok");
  });

  it("opens a failed run on its failed step in a loop, one of its iterations at a time", async () => {
    answers.set(RUN_PATH, json({ ...loopRun, status: "failed", error: { code: "invalid_blocks", message: "Slack refused the message's blocks." } }));
    show();
    const side = await screen.findByRole("complementary", { name: "notify" });
    expect(within(side).getByText("120 instances: 14 succeeded · 3 failed · 103 skipped")).toBeTruthy();
    expect(await within(side).findByRole("combobox", { name: "Iteration" })).toBeTruthy();
  });
});

describe("cancel (§5.3; the RunRunning board)", () => {
  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
  const CANCEL = `${RUN_PATH}/cancel`;
  const running: Run = { ...RUN, status: "running", ended_at: null, error: null };
  const requested = { cancel: "requested", request: { id: RUN.id, workflow_id: "w1", version_id: "v2", draft_snapshot_id: null, target_step_id: null,
    mode: "live", source: "webhook", status: "started", reason: null, queued_at: RUN.queued_at, ended_at: null } };  // prettier-ignore
  const posts = () => reads.filter((r) => r === CANCEL).length;

  beforeEach(() => answers.set(RUN_PATH, json(running)));

  it("asks before cancelling a live run, then says it's requested until the server confirms it", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
    const ask = screen.getByRole("alertdialog", { name: "Cancel this run?" });
    expect(within(ask).getByText("It stops at its next step. What it already did against Mist and its other connections isn't undone.")).toBeTruthy();
    await userEvent.click(within(ask).getByRole("button", { name: "Keep it running" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posts()).toBe(0);
    answers.set(CANCEL, json(requested));
    await userEvent.click(screen.getByRole("button", { name: "Cancel the run" }));
    answers.set(RUN_PATH, json({ ...running, cancel_requested_at: local(10, 2, 20) }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel the run" }));
    expect(await within(bar()).findByText("Cancel requested")).toBeTruthy();
    expect(within(bar()).queryByText("Running")).toBeNull();
    expect(screen.getByText("It's shown as cancelled once the server confirms it.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
    expect(posts()).toBe(1);
    expect(said).toContain("Cancel requested. It's shown as cancelled once the server confirms it.");
    stop();
  });

  it("gives focus to the run's name once a live run's cancel is sent and its question has closed (its Cancel is gone)", async () => {
    const order: string[] = [];
    const close = vi.spyOn(HTMLDialogElement.prototype, "close");
    close.mockImplementation(function (this: HTMLDialogElement) {
      order.push("closed");
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    });
    answers.set(CANCEL, json(requested));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
    const title = screen.getByRole("heading", { level: 1, name: "AP offline triage" });
    title.addEventListener("focus", () => order.push("title focused"));
    answers.set(RUN_PATH, json({ ...running, cancel_requested_at: local(10, 2, 20) }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel the run" }));
    await vi.waitFor(() => expect(order).toEqual(["closed", "title focused"]));
    expect(document.activeElement).toBe(title);
  });

  it("cancels a simulated run at once, without asking", async () => {
    answers.set(RUN_PATH, json({ ...running, mode: "simulate" }));
    answers.set(CANCEL, json({ ...requested, request: { ...requested.request, mode: "simulate" } }));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await vi.waitFor(() => expect(posts()).toBe(1));
  });

  it("says when the cancel didn't go through, and offers it again", async () => {
    answers.set(RUN_PATH, json({ ...running, mode: "simulate" }));
    answers.set(CANCEL, json({ error: "internal_error" }, 500));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Couldn't cancel it. Try again.");
    expect(screen.getByRole("button", { name: "Cancel the run" })).toBeTruthy();
    expect(within(bar()).getByText("Running")).toBeTruthy();
  });

  it("offers no Cancel to a role without run.cancel, nor on a run that ended", async () => {
    role = "viewer";
    show();
    await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
    await vi.waitFor(() => expect(reads).toContain("/api/v1/t/t1"));
    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
    cleanup();
    role = "operator";
    answers.set(RUN_PATH, json(RUN));
    show();
    await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
    await vi.waitFor(() => expect(reads.filter((r) => r === "/api/v1/t/t1")).toHaveLength(2));
    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
  });

  it("reads a run cancelled while it waited as cancelled, never as a cancel requested", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    const queued: Run = { ...running, status: "queued", started_at: null, request: { status: "queued", source: "webhook", reason: null } };
    answers.set(RUN_PATH, json(queued));
    answers.set(CANCEL, json({ ...requested, cancel: "cancelled", request: { ...requested.request, status: "cancelled" } }));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel the run" }));
    answers.set(RUN_PATH, json({ ...queued, status: "cancelled", ended_at: local(10, 2, 20), request: { ...queued.request!, status: "cancelled" } }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel the run" }));
    expect(await within(bar()).findByText("Cancelled")).toBeTruthy();
    expect(screen.queryByText("Cancel requested")).toBeNull();
    await vi.waitFor(() => expect(said).toContain("Run ended: cancelled"));
    expect(said).not.toContain("Cancel requested. It's shown as cancelled once the server confirms it.");
    stop();
  });
});

describe("runs that didn't run, and others (§5.4; the RunOther board)", () => {
  const RUN_PATH = `/api/v1/t/t1/runs/${RUN.id}`;
  const unstarted = (status: Run["status"], reason: string | null = null): Run => ({
    ...RUN, status, started_at: null, ended_at: status === "queued" ? null : RUN.queued_at, error: null,
    request: { status: status === "running" ? "started" : (status as "queued"), source: "webhook", reason },
  });  // prettier-ignore
  const notReached: RunSteps = { given: "input", steps: FAILED_STEPS.steps.map((s) => ({ ...s, origin: "not_reached_yet", instances: 0, statuses: {}, final: null })) };

  it("says a run is waiting to start, its steps without tags, with Cancel", async () => {
    answers.set(RUN_PATH, json(unstarted("queued")));
    answers.set(`${RUN_PATH}/steps`, json(notReached));
    show();
    expect((await screen.findByText(/^Waiting to start/)).textContent).toBe("Waiting to start · queued today 09:41:12. Nothing has run yet.");
    await vi.waitFor(() => expect(reads).toContain(`${RUN_PATH}/steps`));
    await vi.waitFor(() => expect(canvas().dataset.results).toBe("[]"));
    expect(screen.queryByRole("note")).toBeNull(); // nothing has acted yet
    expect(await screen.findByRole("button", { name: "Cancel the run" })).toBeTruthy();
  });

  it("says why a run couldn't start, or was refused, by its code, and that nothing ran", async () => {
    answers.set(RUN_PATH, json(unstarted("dead", "start_throttled")));
    show();
    expect((await screen.findByText(/^start_throttled/)).closest("p")!.textContent).toBe("start_throttled · Too many runs were starting at once. Nothing ran.");
    expect(within(bar()).getByText("Couldn't start")).toBeTruthy();
    cleanup();
    answers.set(RUN_PATH, json(unstarted("refused", "input_invalid")));
    show();
    expect((await screen.findByText(/^input_invalid/)).closest("p")!.textContent).toBe("input_invalid · Its input didn't fit the workflow's input. Nothing ran.");
    expect(screen.queryByRole("button", { name: "Cancel the run" })).toBeNull();
  });

  it("says there are no steps to show for a request refused before a version of the workflow was chosen", async () => {
    answers.set(RUN_PATH, json({ ...unstarted("refused", "workflow_disabled"), version_id: null, draft_snapshot_id: null }));
    answers.set(`${RUN_PATH}/steps`, json({ given: "input", steps: [] }));
    show();
    expect(await screen.findByText("No version of the workflow was chosen for it, so there are no steps to show.")).toBeTruthy();
    expect(screen.queryByText("Reading the workflow it ran…")).toBeNull();
  });

  it("says an older run doesn't say how each step ended", async () => {
    answers.set(RUN_PATH, json({ ...RUN, outcomes_recorded: false }));
    show();
    expect(await screen.findByText("This run is older than step-by-step results: a step it didn't record shows “not recorded”.")).toBeTruthy();
  });

  describe("its start (the Start drawer)", () => {
    const byHand: Run = { ...RUN, started_by: "nadia@example.com", trigger: { source: "manual", schedule: null, endpoint: null, rerun_of: null } };
    const start = () => within(canvas()).getByRole("button", { name: "Start: by hand, nadia@example.com. Open the run's start" });
    beforeEach(() => answers.set(RUN_PATH, json(byHand)));

    it("says who started it and when, and its input as its request stored it, redacted", async () => {
      answers.set(`${RUN_PATH}/input`, json({ read_back: "kept", input: { org: "Acme Retail", api_token: "[redacted]" }, seeds: null }));
      show();
      await screen.findByRole("complementary", { name: "notify_noc" });
      await userEvent.click(start());
      const side = screen.getByRole("complementary", { name: "Start" });
      await vi.waitFor(() => expect(document.activeElement).toBe(within(side).getByRole("heading", { name: "Start" })));
      expect(within(side).getByText(/^By hand/).textContent).toBe("By hand · nadia@example.com · today 09:41:12");
      const input = within(side).getByRole("region", { name: "Input" });
      expect(await within(input).findByText("As the run's request stored it. Sensitive values are redacted.")).toBeTruthy();
      expect(within(input).getAllByRole("definition").map((d) => d.textContent)).toEqual(['"Acme Retail"', "redacted"]);
      expect(canvas().dataset.current).toBe("");
      await userEvent.click(within(side).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("complementary", { name: "Start" })).toBeNull();
      await vi.waitFor(() => expect(document.activeElement).toBe(start()));
    });

    it("shows a value its start form picked as the name, the id under it, as picked then (the 4f-3 design §5.5)", async () => {
      const LYON = "8a27c4d0-5e1f-4b6a-9c2d-3f4e5a6b7c8d";
      answers.set(`${RUN_PATH}/input`, json({ read_back: "kept", input: { site_id: LYON, ticket: "CHG-1042" }, names: { site_id: "Lyon DC" }, seeds: null }));
      show();
      await screen.findByRole("complementary", { name: "notify_noc" });
      await userEvent.click(start());
      const input = within(screen.getByRole("complementary", { name: "Start" })).getByRole("region", { name: "Input" });
      await vi.waitFor(() => expect(within(input).getAllByRole("definition").map((d) => d.textContent)).toEqual([`Lyon DC${LYON}`, '"CHG-1042"']));
      expect(within(input).getByText(LYON).className).toContain("font-mono");
      expect(within(input).getByText((_, el) => el?.tagName === "P" && el.textContent === "site_id's name as picked when the run started.")).toBeTruthy();
    });

    it("says names, not one, when its start form picked several; a value without a name shows as it is", async () => {
      const input = { site_id: "s1", wlan_id: "w1", ticket: "s1" };
      answers.set(`${RUN_PATH}/input`, json({ read_back: "kept", input, names: { site_id: "Lyon DC", wlan_id: "Guests" }, seeds: null }));
      show();
      await screen.findByRole("complementary", { name: "notify_noc" });
      await userEvent.click(start());
      const region = within(screen.getByRole("complementary", { name: "Start" })).getByRole("region", { name: "Input" });
      await vi.waitFor(() => expect(within(region).getAllByRole("definition").map((d) => d.textContent)).toEqual(["Lyon DCs1", "Guestsw1", '"s1"']));
      expect(within(region).getByText("Names as picked when the run started.")).toBeTruthy();
    });

    it("says when its input isn't kept any more, or can't be read back", async () => {
      answers.set(`${RUN_PATH}/input`, json({ read_back: "absent", input: null, seeds: null }));
      show();
      await screen.findByRole("complementary", { name: "notify_noc" });
      await userEvent.click(start());
      expect(await screen.findByText("Its input isn't kept any more. The run's steps and results still are.")).toBeTruthy();
      cleanup();
      answers.set(`${RUN_PATH}/input`, json({ read_back: "unreadable", input: null, seeds: null }));
      show();
      await screen.findByRole("complementary", { name: "notify_noc" });
      await userEvent.click(start());
      expect(await screen.findByText("Its input can't be read back: it doesn't open, or the tenant's key is gone during an erasure.")).toBeTruthy();
    });

    it("shows a CSV run's file: the rows read, run and skipped, why each was skipped, and its columns", async () => {
      answers.set(RUN_PATH, json({
        ...byHand,
        csv: { row_count: 50, headers: ["site_name", "country"], mapping: { name: "site_name", country_code: "country" },
          skipped: [{ row: 7, code: "missing_value" }, { row: 19, code: "not_a_number" }], errors: [], error_count: 0 },
      }));  // prettier-ignore
      answers.set(`${RUN_PATH}/input`, json({ read_back: "kept", input: {}, seeds: null }));
      show();
      await screen.findByRole("complementary", { name: "notify_noc" });
      await userEvent.click(start());
      const file = await screen.findByRole("region", { name: "CSV file" });
      expect(within(file).getAllByRole("term").map((d) => d.textContent)).toEqual(["Rows", "Skipped", "Columns"]);
      expect(within(file).getAllByRole("definition").map((d) => d.textContent)).toEqual([
        "50 read · 48 run · 2 skipped", "row 7 missing_value · row 19 not_a_number", "site_name → name, country → country_code",
      ]);  // prettier-ignore
    });
  });
});

describe("Re-run… (the run form design §5.1, §5.4; the EntryPoints board)", () => {
  const FORM = { workflow_id: "w1", version_id: "v2", version_number: 2, published_at: local(8, 0, 0), published_by: null, csv: null, fields: [] };
  beforeEach(() => {
    answers.set("/api/v1/t/t1/workflows/w1/start-form", json(FORM));
    answers.set(`/api/v1/t/t1/runs/${RUN.id}/input`, json({ input: {}, read_back: "kept", seeds: null }));
  });

  it("offers Re-run… once the run has ended, to the roles that hold run.start, and opens its form", async () => {
    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Re-run…" }));
    expect(await screen.findByRole("dialog", { name: "Re-run 4a2b17e0" })).toBeTruthy();
    expect(await screen.findByText("It runs version 2, the same version as run 4a2b17e0.")).toBeTruthy();
  });

  it("offers none while the run goes (Cancel instead), on a draft simulation, on a sub-run, nor to a viewer", async () => {
    const cases: [Run, string][] = [
      [{ ...RUN, status: "running", ended_at: null }, "operator"],
      [{ ...RUN, draft_snapshot_id: "s1", draft_revision: 4, mode: "simulate" }, "operator"],
      [{ ...RUN, parent: { run_id: "p1", step_id: null, iteration_key: null }, parent_run_id: "p1" }, "operator"],
      [RUN, "viewer"],
    ];
    for (const [run, as] of cases) {
      role = as;
      answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(run));
      show();
      await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
      await vi.waitFor(() => expect(reads).toContain("/api/v1/t/t1")); // the role read, then drawn
      await act(() => new Promise((r) => setTimeout(r, 0)));
      expect(screen.queryByRole("button", { name: "Re-run…" })).toBeNull();
      if (run.status === "running") expect(screen.getByRole("button", { name: "Cancel the run" })).toBeTruthy();
      cleanup();
      reads = [];
    }
  });
});
