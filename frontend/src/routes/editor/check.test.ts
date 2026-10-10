// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import type { Validation } from "../../lib/workflows";
import { checkLabel, checkState } from "./check";

const answer = (revision: number): Validation => ({
  draft_revision: revision, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] },
  conditional_steps: [],
});  // prettier-ignore
const sync = (revision: number, generation = 0, savedGeneration = generation) => ({ revision, generation, savedGeneration });

it("says nothing reassuring before the first answer", () => {
  expect(checkLabel(checkState({ status: "unchecked" }, sync(1)), 0)).toBe("Not checked");
  expect(checkLabel(checkState({ status: "checking", last: null }, sync(1)), 0)).toBe("Checking…");
});

it("is current only for the saved revision that's on the screen", () => {
  expect(checkState({ status: "done", last: answer(2) }, sync(2, 3))).toBe("current");
  expect(checkState({ status: "done", last: answer(1) }, sync(2, 3))).toBe("stale"); // an older revision's
  expect(checkState({ status: "done", last: answer(2) }, sync(2, 4, 3))).toBe("stale"); // edited since
});

it("says a failed check failed, whatever an earlier one found", () => {
  expect(checkLabel(checkState({ status: "failed", last: answer(2) }, sync(2)), 0)).toBe("Check failed");
});

it("words a stale check by what it found then", () => {
  expect(checkLabel("stale", 0)).toBe("Not checked since your edits");
  expect(checkLabel("stale", 2)).toBe("Problems · 2, before your edits");
  expect(checkLabel("current", 0)).toBe("No problems");
  expect(checkLabel("current", 3)).toBe("Problems · 3");
});
