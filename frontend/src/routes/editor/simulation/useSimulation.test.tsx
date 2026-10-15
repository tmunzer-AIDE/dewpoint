// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { freeze, type SimulationRequest, type SimulationState } from "../../../lib/simulations";
import { useSimulation } from "./useSimulation";

const BASE = "/api/v1/t/t1/workflows/w1/draft/simulations";
type Answer = () => Response | Promise<Response>;
let answers: Map<string, Answer>;
let sent: { method: string; path: string; key: string | null }[];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const request = (status: SimulationRequest["status"], id = "r1"): SimulationRequest => ({
  id, workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null, mode: "simulate",
  source: "manual", status, reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null, admission_checks: [],
});  // prettier-ignore
const state = (status: SimulationRequest["status"], run: SimulationState["run"] = null, cancel_requested = false): SimulationState =>
  ({ request: request(status), run, cancel_requested, read_back: "kept", input: {}, seeds: null });

beforeEach(() => {
  sent = [];
  answers = new Map<string, Answer>([[`GET ${BASE}`, () => json([])]]);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const r = input as Request;
    const path = new URL(r.url).pathname;
    sent.push({ method: r.method, path, key: r.headers.get("Idempotency-Key") });
    const answer = answers.get(`${r.method} ${path}`);
    return answer ? answer() : json({ error: "not_found" }, 404);
  });
});
afterEach(() => vi.restoreAllMocks());

function session() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return renderHook(() => useSimulation("t1", "w1"), { wrapper });
}

describe("a simulation the editor sends (§7.1, §7.2)", () => {
  it("is sent once, then read where it is, and holds Simulate while it hasn't ended", async () => {
    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} }, "k1")));
    await waitFor(() => expect(result.current.phase).toBe("queued"));
    expect(result.current.busy).toBe(true);
    expect(sent.filter((s) => s.method === "POST")).toEqual([{ method: "POST", path: BASE, key: "k1" }]);
  });

  it("whose answer is lost is unknown, and Check again sends the same request, its key unchanged", async () => {
    answers.set(`POST ${BASE}`, () => Promise.reject(new TypeError("network")));
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} }, "k1")));
    expect(result.current.local.kind).toBe("unknown");
    expect(result.current.busy).toBe(true); // it may have started: never a second one meanwhile
    answers.set(`POST ${BASE}`, () => json(request("starting"), 202));
    answers.set(`GET ${BASE}/r1`, () => json(state("starting")));
    await act(() => result.current.checkAgain());
    await waitFor(() => expect(result.current.phase).toBe("starting"));
    expect(sent.filter((s) => s.method === "POST").map((s) => s.key)).toEqual(["k1", "k1"]);
  });

  it("refused says so in the server's words, and leaves Simulate free", async () => {
    answers.set(`POST ${BASE}`, () => json({ error: "csv_not_simulated", messages: ["This draft's input takes a CSV file…"] }, 422));
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} })));
    expect(result.current.local).toMatchObject({ kind: "refused", error: { status: 422, code: "csv_not_simulated" } });
    expect(result.current.busy).toBe(false);
  });

  it("refused by the deployment says so too: a 503 in the server's words isn't a lost answer", async () => {
    answers.set(`POST ${BASE}`, () => json({ error: "production_runs_disabled", messages: ["Production runs are off in this deployment."] }, 503));
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} })));
    expect(result.current.local).toMatchObject({ kind: "refused", error: { status: 503, code: "production_runs_disabled" } });
    answers.set(`POST ${BASE}`, () => new Response("Bad gateway", { status: 502 })); // a proxy's, not the API's
    await act(() => result.current.start(freeze(14, { input: {} })));
    expect(result.current.local.kind).toBe("unknown");
  });

  it("tried again after a refusal is the same request: a refusal is never recorded, so its key is free", async () => {
    answers.set(`POST ${BASE}`, () => json({ error: "no_current_build", messages: ["No current build has been recorded lately."] }, 503));
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} }, "k1")));
    expect(result.current.local.kind).toBe("refused"); // a known answer, not a lost one
    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
    await act(() => result.current.checkAgain());
    await waitFor(() => expect(result.current.phase).toBe("queued"));
    expect(sent.filter((s) => s.method === "POST").map((s) => s.key)).toEqual(["k1", "k1"]);
  });

  it("can be cancelled, and is read again at once", async () => {
    let cancelled = false;
    answers.set(`POST ${BASE}`, () => json(request("started"), 202));
    answers.set(`GET ${BASE}/r1`, () => json(state("started", { status: "running", queued_at: null, started_at: null, ended_at: null, error: null, iterations: 0 }, cancelled)));
    answers.set("POST /api/v1/t/t1/runs/r1/cancel", () => {
      cancelled = true;
      return json({ cancel: "requested", request: request("started") }, 202);
    });
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} })));
    await waitFor(() => expect(result.current.phase).toBe("running"));
    await act(async () => void (await result.current.cancel()));
    await waitFor(() => expect(result.current.phase).toBe("cancel_requested"));
  });

  it("whose read fails keeps the last state it knew, and says so", async () => {
    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} })));
    await waitFor(() => expect(result.current.phase).toBe("queued"));
    answers.set(`GET ${BASE}/r1`, () => json({ error: "unavailable" }, 503));
    act(() => result.current.readAgain());
    await waitFor(() => expect(result.current.readFailed).toBe(true));
    expect(result.current.phase).toBe("queued");
    expect(result.current.asOf).not.toBeNull();
  });

  it("is read again after a second, and not while the tab is hidden (§7.2)", async () => {
    answers.set(`POST ${BASE}`, () => json(request("queued"), 202));
    answers.set(`GET ${BASE}/r1`, () => json(state("queued")));
    const reads = () => sent.filter((s) => s.method === "GET" && s.path === `${BASE}/r1`).length;
    const { result } = session();
    await act(() => result.current.start(freeze(14, { input: {} })));
    await waitFor(() => expect(reads()).toBeGreaterThan(1), { timeout: 3000 }); // read again a second later
    try {
      act(() => focusManager.setFocused(false)); // the tab hidden
      const hidden = reads();
      await new Promise((r) => setTimeout(r, 2500)); // past the next read's time
      expect(reads()).toBe(hidden);
      act(() => focusManager.setFocused(true)); // shown again: read at once
      await waitFor(() => expect(reads()).toBeGreaterThan(hidden));
    } finally {
      focusManager.setFocused(undefined);
    }
  });
});

describe("after a reload (§7.1)", () => {
  it("finds the person's latest simulation of the workflow, labelled as exactly that", async () => {
    answers.set(`GET ${BASE}`, () => json([request("started", "r9")]));
    answers.set(`GET ${BASE}/r9`, () => json({ ...state("started", { status: "succeeded", queued_at: null, started_at: null, ended_at: "2026-10-15T10:42:19Z", error: null, iterations: 1 }), request: request("started", "r9") }));
    const { result } = session();
    await waitFor(() => expect(result.current.phase).toBe("succeeded"));
    expect(result.current.local).toMatchObject({ kind: "admitted", latest: true, frozen: null });
    expect(result.current.busy).toBe(false);
  });
});
