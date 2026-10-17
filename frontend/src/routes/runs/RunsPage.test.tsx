// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, useSearch } from "@tanstack/react-router";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onAnnounce } from "../../lib/announce";
import { PAGE, validateRunsSearch, type RunItem } from "../../lib/runs";
import { item } from "../../test/runs";
import { RunsPage } from "./RunsPage";

// Instants from the person's own clock: what the page says doesn't depend on the zone the tests run in.
const local = (h: number, m: number, s: number, day = 16) => new Date(2026, 9, day, h, m, s).toISOString();
const NOW = new Date(2026, 9, 16, 10, 2, 19).getTime();
const schedule = (cron: string) => ({ source: "schedule" as const, schedule: { cron, every_s: null, offset_s: 0, time_zone: "Europe/Paris" }, endpoint: null, rerun_of: null });
const scheduled = { source: "schedule" as const, status: "started" as const, reason: null };

// The Main board's runs, newest first.
const BOARD: RunItem[] = [
  item("a14b2e9c-0001", local(10, 2, 9), { status: "queued", started_at: null, request: { status: "queued", source: "webhook", reason: null } }),
  item("9f3c2a71-0002", local(10, 2, 7), { status: "running" }),
  item("4a2b17e0-0003", local(9, 41, 12), { status: "failed", ended_at: local(9, 41, 50), error: { code: "channel_not_found", message: "The channel wasn't found." } }),
  item("c81d0e55-0004", local(6, 0, 3), { workflow_name: "Daily device report", ended_at: local(6, 1, 55), trigger: schedule("0 6 * * 1-5"), request: scheduled }),
  item("77e0b9d2-0005", local(5, 47, 40), {
    workflow_name: "Bulk site creation", mode: "simulate", ended_at: local(5, 48, 9), started_by: "nadia@example.com",
    trigger: { source: "manual", schedule: null, endpoint: null, rerun_of: null }, request: { ...scheduled, source: "manual" },
  }),
  item("0be41f3c-0006", local(2, 0, 1, 15), {
    workflow_name: "Weekly PSK rotation", status: "deadline_exceeded", ended_at: local(2, 30, 1, 15),
    error: { code: "deadline_exceeded", message: "The run passed its deadline." }, trigger: schedule("0 2 * * *"), request: scheduled,
  }),
  item("5d9a7c10-0007", local(17, 40, 2, 15), {
    workflow_name: "Enforce auto-upgrade", status: "cancelled", ended_at: local(17, 43, 12, 15), started_by: "nadia@example.com",
    trigger: { source: "rerun", schedule: null, endpoint: null, rerun_of: "2c4f8e91-0000" }, request: { ...scheduled, source: "rerun" },
  }),
  item("e2f7a6b4-0008", local(6, 0, 0, 15), {
    workflow_name: "Daily device report", status: "dead", started_at: null, ended_at: local(6, 0, 40, 15), trigger: schedule("0 6 * * 1-5"),
    request: { status: "dead", source: "schedule", reason: "start_throttled" },
  }),
  item("3c6d1f08-0009", local(1, 0, 0, 15), {
    workflow_name: "Nightly site check", status: "refused", started_at: null, ended_at: local(1, 0, 0, 15), trigger: schedule("0 1 * * *"),
    request: { status: "refused", source: "schedule", reason: "input_invalid" },
  }),
];  // prettier-ignore

const WORKFLOWS = [{ id: "w1", name: "AP offline triage" }, { id: "w2", name: "Bulk AP rename" }];

let answers: (() => Response)[];
let sent: URL[];

beforeEach(() => {
  answers = [];
  sent = [];
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = new URL((input as Request).url);
    if (url.pathname === "/api/v1/t/t1/workflows") return Promise.resolve(new Response(JSON.stringify(WORKFLOWS)));
    sent.push(url);
    return Promise.resolve(answers.shift()?.() ?? new Response(JSON.stringify(BOARD)));
  });
});
afterEach(() => vi.restoreAllMocks());

function Runs() {
  return <RunsPage tenantId="t1" filters={useSearch({ strict: false })} />;
}

/** The Runs page at `path`, its filters in the address as the app's route keeps them. */
function show(path = "/t/t1/runs") {
  const root = createRootRoute();
  const runs = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs", validateSearch: validateRunsSearch, component: Runs });
  const run = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs/$runId" });
  const router = createRouter({ routeTree: root.addChildren([runs, run]), history: createMemoryHistory({ initialEntries: [path] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const cells = (id: string) => within(screen.getByRole("link", { name: id }).closest("tr")!).getAllByRole("cell").map((c) => c.textContent);

it("lists each run: its name, workflow, status, trigger, start, duration and error, as the Main board (§5.2)", async () => {
  show();
  await screen.findByRole("link", { name: "a14b2e9c" });
  expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Run", "Workflow", "Status", "Trigger", "Started", "Duration", "Error"]);
  expect(cells("a14b2e9c")).toEqual(["a14b2e9c", "AP offline triage", "Queued", "WebhookMist events", "today 10:02:09", "—", ""]);
  expect(cells("9f3c2a71")).toEqual(["9f3c2a71", "AP offline triage", "Running", "WebhookMist events", "today 10:02:07", "12 s", ""]);
  expect(cells("4a2b17e0")).toEqual(["4a2b17e0", "AP offline triage", "Failed", "WebhookMist events", "today 09:41:12", "38 s", "channel_not_foundThe channel wasn't found."]);
  expect(cells("c81d0e55")).toEqual(["c81d0e55", "Daily device report", "Succeeded", "ScheduleWeekdays at 06:00", "today 06:00:03", "1 min 52 s", ""]);
  expect(cells("77e0b9d2")).toEqual(["77e0b9d2", "Bulk site creation", "SucceededSimulated", "By handnadia@example.com", "today 05:47:40", "29 s", ""]);
  expect(cells("0be41f3c")).toEqual([
    "0be41f3c", "Weekly PSK rotation", "Ran out of time", "ScheduleEvery day at 02:00", "yesterday 02:00:01", "30 min", "deadline_exceededThe run passed its deadline.",
  ]);  // prettier-ignore
  expect(cells("5d9a7c10")).toEqual(["5d9a7c10", "Enforce auto-upgrade", "Cancelled", "Re-runof 2c4f8e91", "yesterday 17:40:02", "3 min 10 s", ""]);
  expect(cells("e2f7a6b4")).toEqual([
    "e2f7a6b4", "Daily device report", "Couldn't start", "ScheduleWeekdays at 06:00", "yesterday 06:00:00", "—", "start_throttledToo many runs were starting at once. Nothing ran.",
  ]);  // prettier-ignore
  expect(cells("3c6d1f08")[6]).toBe("input_invalidIts input didn't fit the workflow's input. Nothing ran.");
});

it("gives each start's full date and zone on hover (the owner's answer 8)", async () => {
  show();
  const started = within((await screen.findByRole("link", { name: "4a2b17e0" })).closest("tr")!).getByText("today 09:41:12");
  expect(started.tagName).toBe("TIME");
  expect(started.getAttribute("title")).toMatch(/^Friday, 16 October 2026 at 09:41:12 /);
});

it("says a draft simulation is one, and a run whose code it doesn't know by its code alone", async () => {
  answers.push(() => new Response(JSON.stringify([
    item("7c1e9a40-0001", local(10, 0, 0), { mode: "simulate", draft_snapshot_id: "s1" }),
    item("1e8a3f27-0002", local(9, 0, 0), { status: "refused", started_at: null, request: { status: "refused", source: "manual", reason: "a_code_from_later" } }),
  ])));  // prettier-ignore
  show("/t/t1/runs?mode=drafts");
  await screen.findByRole("link", { name: "7c1e9a40" });
  expect(cells("7c1e9a40")[2]).toBe("SucceededDraft simulation");
  expect(cells("1e8a3f27")[6]).toBe("a_code_from_laterNothing ran.");
});

it("names a trigger of a kind it doesn't know by its code, and one named after an object's property as itself", async () => {
  const later = (source: string) => ({ source, schedule: null, endpoint: null, rerun_of: null }) as unknown as RunItem["trigger"];
  answers.push(() => json([
    item("aa000001-0001", local(10, 0, 0), { trigger: later("api") }),
    item("aa000002-0002", local(9, 0, 0), { trigger: later("constructor") }),
  ]));  // prettier-ignore
  show("/t/t1/runs?started=all");
  await screen.findByRole("link", { name: "aa000001" });
  expect(cells("aa000001")[3]).toBe("api");
  expect(cells("aa000002")[3]).toBe("constructor");
});

it("asks for the runs its filters choose", async () => {
  show("/t/t1/runs?status=failed&workflow=w1&started=all");
  await screen.findByRole("link", { name: "a14b2e9c" });
  expect(Object.fromEntries(sent[0]!.searchParams)).toEqual({ status: "failed", workflow_id: "w1", draft: "exclude", limit: "50" });
});

it("opens a run's page from its name", async () => {
  const router = show();
  await userEvent.click(await screen.findByRole("link", { name: "4a2b17e0" }));
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/runs/4a2b17e0-0003"));
});

it("says it's reading the runs, then that none ran yet (the ListStates board)", async () => {
  let open!: () => void;
  const held = new Promise<void>((resolve) => (open = resolve));
  const answer = vi.mocked(globalThis.fetch).getMockImplementation()!;
  vi.mocked(globalThis.fetch).mockImplementation((input) => held.then(() => answer(input)));
  answers.push(() => new Response("[]"));
  show("/t/t1/runs?started=all");
  expect((await screen.findByText("Reading the runs…")).getAttribute("role")).toBe("status");
  open();
  expect(await screen.findByText("No runs yet. A run starts by hand from a workflow, on a schedule, or from a webhook.")).toBeTruthy();
});

it("says the runs couldn't be read, and reads them again when asked", async () => {
  answers.push(() => new Response(JSON.stringify({ error: "internal_error" }), { status: 500 }));
  show();
  expect((await screen.findByRole("alert")).textContent).toBe("The runs couldn't be read.");
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("link", { name: "a14b2e9c" })).toBeTruthy();
});

it("lists the runs as a list below 640 px, each one's facts on its lines (§5.6; the Narrow boards)", async () => {
  const wide = window.matchMedia.bind(window);
  vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...wide(query), matches: true }));
  show();
  const list = await screen.findByRole("list", { name: "Runs" });
  expect(screen.queryByRole("table")).toBeNull();
  const runs = within(list).getAllByRole("listitem");
  expect(runs).toHaveLength(BOARD.length);
  expect(runs[1]!.textContent).toBe("9f3c2a71RunningAP offline triageWebhook, Mist events · today 10:02:07 · 12 s");
  expect(runs[2]!.textContent).toBe("4a2b17e0FailedAP offline triageWebhook, Mist events · today 09:41:12 · 38 schannel_not_foundThe channel wasn't found.");
  expect(runs[4]!.textContent).toBe("77e0b9d2SucceededSimulatedBulk site creationBy hand, nadia@example.com · today 05:47:40 · 29 s");
});

const filter = (name: string) => screen.getByRole("button", { name });
const search = (router: ReturnType<typeof show>) => router.state.matches.at(-1)!.search;

it("offers each filter as a menu showing its value, a set one outlined in the accent (§5.2; the ListStates board)", async () => {
  show("/t/t1/runs?status=failed");
  await screen.findByRole("link", { name: "a14b2e9c" });
  const group = screen.getByRole("group", { name: "Filters" });
  expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
    "Workflow · Any ▾", "Status · Failed ▾", "Trigger · Any ▾", "Mode · Live and simulated ▾", "Started · Last 24 hours ▾",
  ]);  // prettier-ignore
  expect(filter("Status · Failed").className).toContain("border-accent");
  expect(filter("Trigger · Any").className).not.toContain("border-accent");
});

it("filters by one status from its menu, keeping the others, in the address (§5.1, §5.2)", async () => {
  const router = show("/t/t1/runs?trigger=schedule");
  await screen.findByRole("link", { name: "a14b2e9c" });
  await userEvent.click(filter("Status · Any"));
  const menu = await screen.findByRole("menu");
  expect(within(menu).getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([
    "✓Any", "Waiting: queued or starting", "Running", "Succeeded", "Failed", "Ran out of time", "Cancelled", "Didn't start: couldn't start or refused",
  ]);  // prettier-ignore
  await userEvent.click(within(menu).getByRole("menuitemradio", { name: "Didn't start: couldn't start or refused" }));
  await vi.waitFor(() => expect(search(router)).toEqual({ trigger: "schedule", status: "didnt_start" }));
  await vi.waitFor(() => expect(sent.at(-1)!.searchParams.get("status")).toBe("didnt_start"));
  expect(filter("Status · Didn't start").className).toContain("border-accent");
});

it("says which runs each mode lists, draft simulations only when chosen (§5.2)", async () => {
  const router = show();
  await screen.findByRole("link", { name: "a14b2e9c" });
  await userEvent.click(filter("Mode · Live and simulated"));
  const menu = await screen.findByRole("menu");
  expect(within(menu).getAllByRole("menuitemradio").map((i) => i.textContent)).toEqual([
    "✓Live and simulated", "Live", "Simulated: of a published version", "Draft simulations: made in the editor", "Everything",
  ]);  // prettier-ignore
  await userEvent.click(within(menu).getByRole("menuitemradio", { name: "Draft simulations: made in the editor" }));
  await vi.waitFor(() => expect(search(router)).toEqual({ mode: "drafts" }));
  expect(sent.at(-1)!.searchParams.get("draft")).toBe("only");
});

it("goes back to a filter's default, leaving it out of the address", async () => {
  const router = show("/t/t1/runs?started=7d");
  await screen.findByRole("link", { name: "a14b2e9c" });
  await userEvent.click(filter("Started · Last 7 days"));
  await userEvent.click(await screen.findByRole("menuitemradio", { name: "Last 24 hours" }));
  await vi.waitFor(() => expect(search(router)).toEqual({}));
});

it("chooses a workflow from a list it can search (§5.2; the ListStates board)", async () => {
  const router = show();
  await screen.findByRole("link", { name: "a14b2e9c" });
  await userEvent.click(filter("Workflow · Any"));
  const chooser = await screen.findByRole("dialog", { name: "Choose a workflow" });
  const find = within(chooser).getByRole("combobox", { name: "Choose a workflow" });
  expect(find.getAttribute("placeholder")).toBe("Find a workflow");
  await userEvent.type(find, "bulk");
  expect(within(chooser).getAllByRole("option").map((o) => o.textContent)).toEqual(["Bulk AP rename"]);
  await userEvent.click(within(chooser).getByRole("option", { name: "Bulk AP rename" }));
  await vi.waitFor(() => expect(search(router)).toEqual({ workflow: "w2" }));
  expect(filter("Workflow · Bulk AP rename").className).toContain("border-accent");
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("says when no run matches the filters, and clears them (the ListStates board)", async () => {
  answers.push(() => new Response("[]"));
  const router = show("/t/t1/runs?status=failed&trigger=webhook");
  expect(await screen.findByText("No runs match these filters in the last 24 hours.")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Clear the filters" }));
  await vi.waitFor(() => expect(search(router)).toEqual({}));
});

it("says no run started in the last 24 hours, never that none ran, and offers every run kept", async () => {
  answers.push(() => new Response("[]"));
  const router = show();
  expect(await screen.findByText("No runs in the last 24 hours.")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Show all kept" }));
  await vi.waitFor(() => expect(search(router)).toEqual({ started: "all" }));
});

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const shownIds = () => within(screen.getByRole("region", { name: "Runs" })).getAllByRole("link").map((l) => l.textContent);

describe("reading the list again (§5.2)", () => {
  // Timers the test moves on, and real time besides, so the page's own waits still pass.
  beforeEach(() => void vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"], shouldAdvanceTime: true }));
  afterEach(() => void vi.useRealTimers());

  it("reads the first page again every 5 s, saying so by the title, new runs at the top, and says it was updated (§5.6)", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    show();
    await screen.findByRole("link", { name: "a14b2e9c" });
    expect(screen.getByText("Updates every 5 s")).toBeTruthy();
    const reads = sent.length;
    answers.push(() => json(BOARD)); // the same: nothing to say
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(sent.length).toBe(reads + 1);
    answers.push(() => json([item("b7d0c3e1-0010", local(10, 2, 15), { status: "queued", started_at: null }), ...BOARD]));
    await act(() => vi.advanceTimersByTimeAsync(5000));
    await vi.waitFor(() => expect(shownIds().slice(0, 2)).toEqual(["b7d0c3e1", "a14b2e9c"]));
    expect(said).toEqual(["Updated"]);
    stop();
  });

  it("isn't read again while the tab is hidden, and is at once when it's shown", async () => {
    show();
    await screen.findByRole("link", { name: "a14b2e9c" });
    const reads = sent.length;
    try {
      act(() => focusManager.setFocused(false));
      await act(() => vi.advanceTimersByTimeAsync(12_000));
      expect(sent.length).toBe(reads);
      act(() => focusManager.setFocused(true));
      await vi.waitFor(() => expect(sent.length).toBeGreaterThan(reads));
    } finally {
      focusManager.setFocused(undefined);
    }
  });

  it("keeps the list when a refresh fails, says as of when, and tries again (the ListStates board)", async () => {
    const said: string[] = [];
    const stop = onAnnounce((m) => said.push(m));
    show();
    await screen.findByRole("link", { name: "a14b2e9c" });
    answers.push(() => json({ error: "internal_error" }, 500));
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(await screen.findByText("Couldn't be refreshed · as of 10:02:19")).toBeTruthy();
    expect(screen.getByRole("link", { name: "a14b2e9c" })).toBeTruthy();
    expect(said).toEqual(["The runs couldn't be refreshed."]);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Updates every 5 s")).toBeTruthy();
    stop();
  });
});

/** `n` runs from minute `from` down, a minute apart, newest first. */
const runsFrom = (from: number, n: number) => Array.from({ length: n }, (_, i) => item(`run${String(from - i).padStart(4, "0")}x-0`, new Date(NOW - (NOW % 60_000) - (1000 - from + i) * 60_000).toISOString()));

it("loads older runs on from the last listed, never reading them again, each once, until none older is kept (§5.2)", async () => {
  const first = runsFrom(1000, PAGE);
  const second = [first.at(-1)!, ...runsFrom(1000 - PAGE, PAGE - 1)]; // the boundary's run read again: listed once
  const third = runsFrom(1000 - 2 * PAGE + 1, 3);
  answers.push(() => json(first));
  show("/t/t1/runs?started=7d");
  await screen.findByRole("link", { name: "run1000x" });
  expect(screen.getByText("The 50 most recent first. New runs appear at the top as they're found.")).toBeTruthy();
  answers.push(() => json(second));
  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByRole("link", { name: `run${String(1000 - 2 * PAGE + 2).padStart(4, "0")}x` });
  expect(Object.fromEntries(sent.at(-1)!.searchParams)).toMatchObject({ before: first.at(-1)!.queued_at, before_id: first.at(-1)!.id });
  expect(shownIds()).toHaveLength(2 * PAGE - 1);
  expect(new Set(shownIds()).size).toBe(2 * PAGE - 1);
  answers.push(() => json(third));
  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByText("No older runs in the last 7 days.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  expect(shownIds()).toHaveLength(2 * PAGE + 2);
});

it("keeps Load more where the keys left it while it reads, says it's reading, and reads once", async () => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  answers.push(() => json(runsFrom(1000, PAGE)));
  show("/t/t1/runs?started=all");
  await screen.findByText("run1000x");
  const answer = vi.mocked(globalThis.fetch).getMockImplementation()!;
  vi.mocked(globalThis.fetch).mockImplementation((input) => held.then(() => answer(input)));
  answers.push(() => json(runsFrom(1000 - PAGE, 3)));
  const more = screen.getByRole("button", { name: "Load more" });
  const calls = () => vi.mocked(globalThis.fetch).mock.calls.length;
  more.focus();
  await userEvent.keyboard("{Enter}");
  const asked = calls();
  expect(more.hasAttribute("disabled")).toBe(false); // a disabled button would drop the keyboard's focus
  expect(more.getAttribute("aria-disabled")).toBe("true");
  expect(document.activeElement).toBe(more);
  expect(screen.getByText("Reading older runs…")).toBeTruthy();
  await userEvent.keyboard("{Enter}");
  expect(calls()).toBe(asked); // the second Enter read nothing
  release();
  expect(await screen.findByText("No older runs are kept.")).toBeTruthy();
});

it("says no older run is kept at all once every run kept is listed", async () => {
  answers.push(() => json(runsFrom(1000, PAGE)), () => json([]));
  show("/t/t1/runs?started=all");
  await screen.findByRole("link", { name: "run1000x" });
  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByText("No older runs are kept.")).toBeTruthy();
});

it("starts the list afresh when a filter changes after older runs were loaded", async () => {
  const newer = runsFrom(2000, PAGE).map((r) => ({ ...r, status: "failed" as const }));
  answers.push(() => json(runsFrom(1000, PAGE)), () => json(runsFrom(1000 - PAGE, 3)), () => json(newer));
  const router = show();
  await screen.findByRole("link", { name: "run1000x" });
  await userEvent.click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByText("No older runs in the last 24 hours.")).toBeTruthy();
  await act(() => router.navigate({ to: "/t/$tenantId/runs", params: { tenantId: "t1" }, search: { status: "failed" } }));
  await screen.findByRole("link", { name: "run2000x" });
  expect(shownIds()).toHaveLength(PAGE); // none of the earlier filters' runs below them
  expect(screen.queryByText("No older runs in the last 24 hours.")).toBeNull();
  expect(screen.getByRole("button", { name: "Load more" })).toBeTruthy();
});
