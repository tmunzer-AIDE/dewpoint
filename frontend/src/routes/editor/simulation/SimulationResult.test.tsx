// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/client";
import type { SimulationRequest, SimulationState, StepSummary } from "../../../lib/simulations";
import type { GraphDoc } from "../../../lib/workflows";
import { SimulationResult } from "./SimulationResult";
import type { SimulationSession } from "./useSimulation";

const request = (over: Partial<SimulationRequest> = {}): SimulationRequest => ({
  id: "r1", workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null, mode: "simulate",
  source: "manual", status: "started", reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [], ...over,
});  // prettier-ignore
const step = (key: string, over: Partial<StepSummary> = {}): StepSummary => ({
  step_id: `id-${key}`, key, type: "testkit.echo@1", origin: "fixture_not_sent", instances: 1, statuses: { succeeded: 1 }, ports: {},
  final: { attempt: 1, status: "succeeded" }, ...over,
});  // prettier-ignore
const node = (key: string, type: string) => ({ id: `id-${key}`, key, type, config: {} });
const DOC = {
  graph_format: 1,
  nodes: [node("get_site", "testkit.echo@1"), node("each_ap", "flow.loop@1"), node("notify", "slack.post@1"), node("wait_10m", "flow.delay@1")],
  edges: [{ from: { node: "id-each_ap", port: "body" }, to: { node: "id-notify" } }, { from: { node: "id-each_ap", port: "done" }, to: { node: "id-wait_10m" } }],
} as unknown as GraphDoc;  // prettier-ignore
const STEPS = [
  step("get_site"),
  step("each_ap", { type: "flow.loop@1", origin: "evaluated", final: { attempt: 1, status: "succeeded", output: { items: [], failures: [], count: 2 } } }),
  step("notify", { instances: 2, statuses: { succeeded: 1, skipped: 1 }, final: null }),
  step("wait_10m", { type: "flow.delay@1", origin: "evaluated_not_waited" }),
  step("gone", { origin: "didnt_run", instances: 0, statuses: {}, final: null }),
];

function session(over: { phase?: SimulationSession["phase"]; state?: Partial<SimulationState>; request?: Partial<SimulationRequest>; steps?: StepSummary[] } = {}): SimulationSession {
  const state: SimulationState = { request: request(over.request), run: null, cancel_requested: false, read_back: "kept", input: { site: "HQ Paris", floor: 3, api_token: "[redacted]" }, seeds: null, ...over.state };
  return {
    local: { kind: "admitted", frozen: null, request: state.request, latest: false }, state, steps: { given: "input", steps: over.steps ?? STEPS },
    phase: over.phase ?? "succeeded", busy: false, readFailed: false, asOf: null, start: vi.fn(), checkAgain: vi.fn(), cancel: vi.fn(), readAgain: vi.fn(),
  };  // prettier-ignore
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = new URL((input as Request).url);
    if (url.pathname.endsWith("/steps/id-notify/instances")) {
      return Promise.resolve(json({ total: 2, items: [
        { step_id: "id-notify", key: "notify", iteration_key: "each_ap:0", attempt: 1, status: "succeeded" },
        { step_id: "id-notify", key: "notify", iteration_key: "each_ap:1", attempt: 1, status: "skipped" },
      ] }));  // prettier-ignore
    }
    return Promise.resolve(json({ error: "not_found" }, 404));
  });
});
afterEach(() => vi.restoreAllMocks());

function show(s: SimulationSession, over: Partial<Parameters<typeof SimulationResult>[0]> = {}) {
  const onGoTo = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SimulationResult
        tenantId="t1" workflowId="w1" session={s} doc={DOC} ran={null} stale={null} changes={null} attemptsOf={() => 3} onGoTo={onGoTo}
        onShowProblems={vi.fn()} {...over}
      />
    </QueryClientProvider>,
  );  // prettier-ignore
  return { onGoTo };
}
const section = (name: string) => screen.getByRole("region", { name });

describe("the Simulation panel's result (§7.5; the ResultPanel board)", () => {
  it("says what a simulation proves, and that a flow timer wasn't waited", () => {
    show(session());
    expect(screen.getByText("Simulated.").parentElement?.textContent).toBe("Simulated. Nothing was sent. Results don't prove the live call will succeed.");
    expect(screen.getByText("Flow delays and wait-until weren't waited; the simulation clock wasn't advanced.")).toBeTruthy();
  });

  it("lists the checks the server found at admission, each with Go to", async () => {
    const check = { code: "connection.missing", message: "The connection “Slack ops” no longer exists.", node: "id-notify", field: null, fix: null, severity: "warning" as const };
    const { onGoTo } = show(session({ request: { admission_checks: [check] } }));
    const checks = section("Checks on the server");
    expect(within(checks).getByText("Found when the simulation was admitted. They didn't stop it; a live run would meet them.")).toBeTruthy();
    expect(within(checks).getByText("The connection “Slack ops” no longer exists.")).toBeTruthy();
    await userEvent.click(within(checks).getByRole("button", { name: "Go to notify" }));
    expect(onGoTo).toHaveBeenCalledWith("id-notify");
  });

  it("lists the steps in run order, with their tags and Go to", async () => {
    const { onGoTo } = show(session());
    const steps = section("Steps, in run order");
    const rows = within(steps).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("[data-key]")?.textContent)).toEqual(["get_site", "each_ap", "notify", "wait_10m", "gone"]);
    expect(within(rows[0]!).getByText("fixture · not sent")).toBeTruthy();
    expect(within(rows[2]!).getByText("2 instances: 1 succeeded · 1 skipped")).toBeTruthy();
    expect(within(rows[3]!).getByText("evaluated · not waited")).toBeTruthy();
    expect(within(rows[4]!).getByText("didn't run")).toBeTruthy();
    expect(within(rows[4]!).queryByRole("button", { name: /^Go to/ })).toBeNull(); // not in the draft any more
    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Go to get_site" }));
    expect(onGoTo).toHaveBeenCalledWith("id-get_site");
  });

  it("opens a loop's iterations under it", async () => {
    show(session());
    const toggle = screen.getByRole("button", { name: "Iterations of each_ap" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(await screen.findByRole("list", { name: "each_ap's iterations, 1 to 2 of 2" })).toBeTruthy();
  });

  it("while it runs, lists only the steps reached so far, and no banner", () => {
    show(session({ phase: "running", steps: [step("get_site"), step("each_ap", { type: "flow.loop@1", origin: "evaluated", statuses: { running: 1 }, final: { attempt: 1, status: "running" } }), step("notify", { origin: "not_reached_yet", instances: 0, statuses: {}, final: null })] }));
    const rows = within(section("Steps so far")).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("[data-key]")?.textContent)).toEqual(["get_site", "each_ap"]);
    expect(screen.queryByText("Simulated.")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Iterations of/ })).toBeNull();
  });

  it("shows the input used as the request stored it, sensitive values redacted", () => {
    show(session());
    const used = section("Input used");
    expect(within(used).getByText("As this simulation's request stored it, sensitive values redacted.")).toBeTruthy();
    const pairs = within(used).getAllByRole("term").map((t) => `${t.textContent}=${t.nextElementSibling?.textContent}`);
    expect(pairs).toEqual(["site=HQ Paris", "floor=3", "api_token=redacted"]);
  });

  it("says when the input used isn't kept any more", () => {
    show(session({ state: { read_back: "absent", input: null } }));
    expect(within(section("Input used")).getByText("The input used isn't kept any more.")).toBeTruthy();
  });

  it("says when the input used can't be read back", () => {
    show(session({ state: { read_back: "unreadable", input: null } }));
    expect(within(section("Input used")).getByText("The input used couldn't be read back.")).toBeTruthy();
  });
});

describe("a result before the person's edits, and what failed (§7.7; the Stale and Refusals boards)", () => {
  it("says it's for an older revision, and marks each step changed since, or no longer in the draft", () => {
    show(session(), { stale: { kind: "revision", from: 14, to: 16 }, changes: { changed: new Set(["id-notify"]), added: new Set(), gone: new Set(["id-gone"]) } });
    expect(screen.getByText("Before your edits:").parentElement?.textContent).toBe(
      "Before your edits: this result is for revision 14; the draft is at revision 16. Simulate again to see the draft as it is.",
    );
    const rows = within(section("Steps, in run order")).getAllByRole("listitem");
    expect(within(rows[2]!).getByText("changed since")).toBeTruthy();
    expect(within(rows[2]!).getByRole("button", { name: "Go to notify" })).toBeTruthy();
    expect(within(rows[4]!).getByText("no longer in the draft")).toBeTruthy();
  });

  it("says a failed step's code and message, its attempts, and that nothing was sent", () => {
    const failed = (key: string, attempt: number, code: string, message: string) =>
      step(key, { statuses: { failed: 1 }, final: { attempt, status: "failed", error: { code, message } } });
    show(session({ phase: "failed", steps: [failed("post_ticket", 1, "simulation_unavailable", "http.request@1 can't be simulated."), failed("notify", 3, "invalid_blocks", "Block 2 has no text.")] }));
    expect(screen.getByText("simulation_unavailable").parentElement?.textContent).toBe("simulation_unavailable http.request@1 can't be simulated. 1 attempt. Nothing was sent.");
    expect(screen.getByText("invalid_blocks").parentElement?.textContent).toBe("invalid_blocks Block 2 has no text. 3 attempts, the configured retries. Nothing was sent.");
  });

  it("shows a refusal in the server's words", () => {
    const s = session();
    s.local = { kind: "refused", frozen: { key: "k1", revision: 14, body: { input: {} } }, error: new ApiError(503, "production_runs_disabled", { error: "production_runs_disabled", messages: ["Production runs are off in this deployment."] }) };
    s.state = null;
    s.phase = null;
    show(s);
    expect(screen.getByText("Not simulated")).toBeTruthy();
    expect(screen.getByText("Production runs are off in this deployment.")).toBeTruthy();
  });

  it("for a step test, says it ran the step alone, and shows the values used, not an input", () => {
    const s = session({ request: { target_step_id: "id-get_site" }, state: { input: null, seeds: { "/vars/region": "emea" } }, steps: [step("get_site")] });
    show(s);
    expect(screen.getByText("Step test: get_site.").parentElement?.textContent).toBe("Step test: get_site. Only this step ran. Nothing was sent.");
    expect(screen.queryByRole("region", { name: "Input used" })).toBeNull();
    expect(within(section("Values used")).getByText("emea")).toBeTruthy();
  });

  it("pages a loop's iterations over the draft it ran, whatever the draft is now", async () => {
    show(session(), { doc: { ...DOC, edges: [] }, ran: DOC });
    await userEvent.click(screen.getByRole("button", { name: "Iterations of each_ap" }));
    expect(await screen.findByRole("list", { name: "each_ap's iterations, 1 to 2 of 2" })).toBeTruthy();
  });
});
