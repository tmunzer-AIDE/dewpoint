// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { StepSummary } from "../../../lib/simulations";
import { tagsOf, words } from "./results";

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
