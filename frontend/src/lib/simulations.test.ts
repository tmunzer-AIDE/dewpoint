// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import {
  ENDED, cancelSimulation, freeze, phaseOf, pollEvery, sendSimulation, type SimulationRequest, type SimulationState,
} from "./simulations";  // prettier-ignore

const request = (status: SimulationRequest["status"]): SimulationRequest => ({
  id: "r1", workflow_id: "w1", draft_snapshot_id: "s1", draft_revision: 14, target_step_id: null,
  mode: "simulate", source: "manual", status, reason: null, queued_at: "2026-10-15T10:42:05Z", ended_at: null,
  admission_checks: [],
});  // prettier-ignore

const state = (
  status: SimulationRequest["status"],
  run: SimulationState["run"] = null,
  cancel_requested = false,
): SimulationState => ({ request: request(status), run, cancel_requested, read_back: "kept", input: {}, seeds: null });

const run = (status: NonNullable<SimulationState["run"]>["status"]): SimulationState["run"] => ({
  status, queued_at: null, started_at: "2026-10-15T10:42:06Z", ended_at: null, error: null, iterations: 0,
});

describe("where a simulation is (§7.2)", () => {
  it("follows its request until its run is written, then its run", () => {
    expect(phaseOf(state("queued"))).toBe("queued");
    expect(phaseOf(state("starting"))).toBe("starting");
    expect(phaseOf(state("started"))).toBe("starting"); // the run row isn't read yet
    expect(phaseOf(state("started", run("running")))).toBe("running");
    expect(phaseOf(state("started", run("succeeded")))).toBe("succeeded");
    expect(phaseOf(state("started", run("deadline_exceeded")))).toBe("deadline_exceeded");
    expect(phaseOf(state("refused"))).toBe("refused");
    expect(phaseOf(state("dead"))).toBe("dead");
    expect(phaseOf(state("cancelled"))).toBe("cancelled"); // cancelled while queued
  });

  it("says a cancel was requested until the server confirms it, never that it's cancelled", () => {
    expect(phaseOf(state("starting", null, true))).toBe("cancel_requested");
    expect(phaseOf(state("started", run("running"), true))).toBe("cancel_requested");
    expect(phaseOf(state("started", run("cancelled"), true))).toBe("cancelled");
    expect(phaseOf(state("started", run("succeeded"), true))).toBe("succeeded"); // it ended before the cancel landed
  });

  it("knows which phases have ended", () => {
    expect([...ENDED].sort()).toEqual(["cancelled", "dead", "deadline_exceeded", "failed", "refused", "succeeded"]);
  });
});

describe("how often it's read again (§7.2)", () => {
  it("starts at 1 s and backs off to 5 s", () => {
    expect([0, 1, 2, 3, 4, 5, 20].map(pollEvery)).toEqual([1000, 1000, 2000, 3000, 5000, 5000, 5000]);
  });
});

describe("one request per submit (§7.1)", () => {
  it("is frozen with a key of its own, sent again as it is", () => {
    const a = freeze(14, { input: { site: "HQ" } });
    const b = freeze(14, { input: { site: "HQ" } });
    expect(a.key).not.toBe(b.key);
    expect(a).toMatchObject({ revision: 14, body: { input: { site: "HQ" } } });
  });
});

describe("the requests it makes", () => {
  let sent: { method: string; path: string; headers: Headers; body: unknown }[];
  let answer: () => Response;
  beforeEach(() => {
    sent = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const r = input as Request;
      const text = await r.text();
      sent.push({ method: r.method, path: new URL(r.url).pathname, headers: r.headers, body: text ? JSON.parse(text) : null });
      return answer();
    });
  });
  afterEach(() => vi.restoreAllMocks());
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  it("sends a simulation with its key and the revision it was frozen at", async () => {
    answer = () => json(request("queued"), 202);
    const frozen = freeze(14, { target: { step_id: "n1", values: { "/vars/x": 1 }, absent: [] } }, "k1");
    expect((await sendSimulation("t1", "w1", frozen)).id).toBe("r1");
    expect(sent[0]).toMatchObject({ method: "POST", path: "/api/v1/t/t1/workflows/w1/draft/simulations" });
    expect(sent[0]!.headers.get("Idempotency-Key")).toBe("k1");
    expect(sent[0]!.headers.get("If-Match")).toBe("14");
    expect(sent[0]!.body).toEqual({ target: { step_id: "n1", values: { "/vars/x": 1 }, absent: [] } });
  });

  it("says a refusal in the server's code", async () => {
    answer = () => json({ error: "draft_conflict", draft_revision: 15 }, 409);
    await expect(sendSimulation("t1", "w1", freeze(14, { input: {} }))).rejects.toMatchObject(
      new ApiError(409, "draft_conflict", { error: "draft_conflict", draft_revision: 15 }),
    );
  });

  it("cancels through the run's own route, saying whether it's done or requested", async () => {
    answer = () => json({ cancel: "requested", request: request("starting") }, 202);
    expect(await cancelSimulation("t1", "r1")).toBe("requested");
    expect(sent[0]).toMatchObject({ method: "POST", path: "/api/v1/t/t1/runs/r1/cancel" });
  });
});
