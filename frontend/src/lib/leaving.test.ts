// SPDX-License-Identifier: Apache-2.0
import { expect, it, vi } from "vitest";
import { cancelLeaving, guardLeaving, mayLeave, unsavedWork } from "./leaving";

it("lets leaving go on only when every open editor agrees, asking each in turn", async () => {
  expect(await mayLeave()).toBe(true); // nothing open
  const first = vi.fn(() => Promise.resolve(true));
  const second = vi.fn(() => Promise.resolve(false));
  const third = vi.fn(() => Promise.resolve(true));
  const stops = [first, second, third].map((decide) => guardLeaving({ unsaved: () => false, decide }));
  expect(await mayLeave()).toBe(false);
  expect([first, second, third].map((f) => f.mock.calls.length)).toEqual([1, 1, 0]); // stops at the first "stay"
  stops.forEach((stop) => stop());
  expect(await mayLeave()).toBe(true);
});

it("withdraws every editor's \"leave\" when the exit doesn't happen", () => {
  const stayed = vi.fn();
  const stop = guardLeaving({ unsaved: () => true, decide: () => Promise.resolve(true), stayed });
  cancelLeaving();
  expect(stayed).toHaveBeenCalledOnce();
  stop();
});

it("says whether any open editor holds unsaved work", () => {
  let dirty = false;
  const stop = guardLeaving({ unsaved: () => dirty, decide: () => Promise.resolve(true) });
  expect(unsavedWork()).toBe(false);
  dirty = true;
  expect(unsavedWork()).toBe(true);
  stop();
  expect(unsavedWork()).toBe(false);
});
