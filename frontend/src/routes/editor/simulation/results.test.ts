// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { RunStepSummary } from "../../../lib/runs";
import type { StepSummary } from "../../../lib/simulations";
import { tagsFitBeside, tagsOf, words } from "./results";

type Final = NonNullable<StepSummary["final"]>;
const summary = (over: Partial<StepSummary>): StepSummary => ({
  step_id: "id-a", key: "a", type: "testkit.echo@1", origin: "fixture_not_sent", instances: 1, statuses: { succeeded: 1 },
  ports: {}, final: null, ...over,
});  // prettier-ignore
const final = (over: Partial<Final> = {}): Final => ({ attempt: 1, status: "succeeded", output: null, input: null, effect: null, ...over });

describe("a step's result on the canvas (§7.3, §7.4; the ResultCanvas and Running boards)", () => {
  it("shows a step that ran once by its final attempt, and where its data came from", () => {
    expect(words(tagsOf(summary({ final: final() }), { maxAttempts: 3, ended: true }))).toEqual(["succeeded", "fixture · not sent"]);
    expect(words(tagsOf(summary({ final: final({ attempt: 2 }) }), { maxAttempts: 3, ended: true }))).toEqual(["succeeded", "attempt 2 of 3", "fixture · not sent"]);
  });

  it("says the port a branch took beside its evaluation, and that a timer wasn't waited", () => {
    const ifStep = summary({ type: "flow.if@1", origin: "evaluated", final: final({ effect: { port: "true" } }), ports: { true: 1 } });
    expect(words(tagsOf(ifStep, { maxAttempts: 1, ended: true }))).toEqual(["succeeded", "evaluated · → true"]);
    const delay = summary({ type: "flow.delay@1", origin: "evaluated_not_waited", final: final() });
    expect(words(tagsOf(delay, { maxAttempts: 1, ended: true }))).toEqual(["succeeded", "evaluated · not waited"]);
  });

  it("gives a loop its iterations once it ended, and its items while it runs", () => {
    const loop = summary({ type: "flow.loop@1", origin: "evaluated", final: final({ output: { items: [], failures: [], count: 12 } }) });
    expect(words(tagsOf(loop, { maxAttempts: 1, ended: true }))).toEqual(["succeeded", "12 iterations"]);
    const running = summary({ type: "flow.loop@1", origin: "evaluated", statuses: { running: 1 }, final: final({ status: "running", input: { items: [1, 2, 3] } }) });
    expect(words(tagsOf(running, { maxAttempts: 1, ended: false }))).toEqual(["running", "3 items"]);
    const cut = summary({ type: "flow.loop@1", origin: "evaluated", final: final({ output: "[truncated]" }) });
    expect(words(tagsOf(cut, { maxAttempts: 1, ended: true }))).toEqual(["succeeded"]);
  });

  it("totals a step's instances over every opened iteration, skipped ones included, its ports apart", () => {
    const notify = summary({ instances: 12, statuses: { succeeded: 1, failed: 2, skipped: 9 } });
    expect(words(tagsOf(notify, { maxAttempts: 3, ended: true }))).toEqual(["12 instances: 1 succeeded · 2 failed · 9 skipped", "fixture · not sent"]);
    const branch = summary({ type: "flow.if@1", origin: "evaluated", instances: 12, statuses: { succeeded: 12 }, ports: { true: 3, false: 9 } });
    expect(words(tagsOf(branch, { maxAttempts: 1, ended: true }))).toEqual(["12 instances: 12 succeeded", "evaluated", "→ true ×3", "→ false ×9"]);
    const sofar = summary({ instances: 4, statuses: { succeeded: 1, failed: 1, skipped: 2 } });
    expect(words(tagsOf(sofar, { maxAttempts: 3, ended: false }))).toEqual(["So far, 4 instances: 1 succeeded · 1 failed · 2 skipped", "fixture · not sent"]);
  });

  it("says why a step has no result, in words", () => {
    expect(words(tagsOf(summary({ instances: 0, statuses: {}, origin: "didnt_run" }), { maxAttempts: 1, ended: true }))).toEqual(["didn't run"]);
    expect(words(tagsOf(summary({ instances: 0, statuses: {}, origin: "not_reached_yet" }), { maxAttempts: 1, ended: false }))).toEqual(["not reached yet"]);
    expect(words(tagsOf(summary({ instances: 1, statuses: { skipped: 1 }, origin: "skipped", final: final({ status: "skipped" }) }), { maxAttempts: 1, ended: true }))).toEqual(["skipped"]);
  });

  it("marks each tag by what it is: a status, a person's values, a fixture, an evaluation, an absence", () => {
    const tags = tagsOf(summary({ final: final() }), { maxAttempts: 3, ended: true });
    expect(tags.map((t) => t.kind)).toEqual(["ok", "fixture"]);
    expect(tagsOf(summary({ instances: 0, statuses: {}, origin: "not_recorded" }), { maxAttempts: 1, ended: true })[0]!.kind).toBe("absent");
  });
});

describe("a run's step on its page (the runs design §5.3; the RunFailed, RunRunning and RunLoop boards)", () => {
  type RunFinal = NonNullable<RunStepSummary["final"]>;
  const at = (s: number) => `2026-10-16T09:41:${String(Math.floor(s)).padStart(2, "0")}.${String(Math.round((s % 1) * 1000)).padStart(3, "0")}Z`;
  const ran = (over: Partial<RunFinal> = {}): RunFinal => ({
    step_id: "id-a", key: "a", iteration_key: "", attempt: 1, status: "succeeded", started_at: at(12), ended_at: at(12.4),
    input: null, output: null, error: null, outcome: null, cel_mode: null, effect: null, ...over,
  });  // prettier-ignore
  const step = (over: Partial<RunStepSummary>): RunStepSummary => ({
    step_id: "id-a", key: "a", type: "mist.get_device@1", origin: "sent", instances: 1, statuses: { succeeded: 1 }, ports: {}, final: ran(), ...over,
  });  // prettier-ignore
  const action = { maxAttempts: 3, ended: true, run: { action: true } };

  it("says a live step sent, and how long it took", () => {
    const tags = tagsOf(step({}), action);
    expect(words(tags)).toEqual(["succeeded", "sent", "0.4 s"]);
    expect(tags.map((t) => t.kind)).toEqual(["ok", "sent", "note"]);
    expect(words(tagsOf(step({ final: ran({ ended_at: at(13.8) }) }), action))).toEqual(["succeeded", "sent", "1.8 s"]);
  });

  it("says a failed step's attempt and its error's code, in place of its time", () => {
    const failed = step({ origin: null, statuses: { failed: 1 }, final: ran({ attempt: 3, status: "failed", error: { code: "channel_not_found", message: "The channel wasn't found." } }) });
    const tags = tagsOf(failed, action);
    expect(words(tags)).toEqual(["failed", "attempt 3 of 3", "channel_not_found"]);
    expect(tags.map((t) => t.kind)).toEqual(["fail", "note", "code"]);
  });

  it("says a step whose answer was lost may have been sent, dashed in the warning's colour", () => {
    const lost = tagsOf(step({ origin: "may_have_been_sent", statuses: { failed: 1 }, final: ran({ status: "failed", error: { code: "outcome_unknown", message: null } }) }), action);
    expect(words(lost)).toEqual(["failed", "may have been sent", "outcome_unknown"]);
    expect(lost[1]!.kind).toBe("maybe");
  });

  it("gives a live control step its port and nothing else: it ran in the engine, and says no origin", () => {
    const branch = step({ type: "flow.if@1", origin: null, final: ran({ effect: { port: "true" } }), ports: { true: 1 } });
    expect(words(tagsOf(branch, { ...action, run: { action: false } }))).toEqual(["succeeded", "→ true"]);
  });

  it("says a running step's attempt, and no time until it ends", () => {
    const running = step({ origin: null, statuses: { running: 1 }, final: ran({ attempt: 2, status: "running", ended_at: null }) });
    expect(words(tagsOf(running, { ...action, ended: false }))).toEqual(["running", "attempt 2 of 3"]);
  });

  it("totals a live loop's step over its instances, and says it sent", () => {
    const notify = step({ instances: 120, statuses: { succeeded: 14, failed: 3, skipped: 103 }, final: null });
    expect(words(tagsOf(notify, action))).toEqual(["120 instances: 14 succeeded · 3 failed · 103 skipped", "sent"]);
    const branch = step({ type: "flow.if@1", origin: null, instances: 120, statuses: { succeeded: 120 }, ports: { true: 17, false: 103 }, final: null });
    expect(words(tagsOf(branch, { ...action, run: { action: false } }))).toEqual(["120 instances: 120 succeeded", "→ true ×17", "→ false ×103"]);
  });
});

describe("where a step's tags go (the review's 1, the owner's choice: beside, else under)", () => {
  it("go beside a card wherever no other card is there, and under it where one is", () => {
    expect(tagsFitBeside({ x: 0, y: 0 }, [{ x: 0, y: 140 }, { x: 600, y: 0 }])).toBe(true); // the next rank, a far card
    expect(tagsFitBeside({ x: 0, y: 0 }, [{ x: 300, y: 0 }])).toBe(false); // a sibling 40 px to the right
    expect(tagsFitBeside({ x: -160, y: 420 }, [{ x: 160, y: 420 }])).toBe(false); // the e2e fixture's branches
    expect(tagsFitBeside({ x: 0, y: 0 }, [{ x: 400, y: 40 }])).toBe(false); // half a card lower, still in the way
  });
});

