// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { LIMIT, begin, record, redo, undo } from "./history";

it("undoes and redoes, and a new change drops what was undone", () => {
  let h = record(record(begin(1), 2), 3);
  h = undo(h);
  expect(h.present).toBe(2);
  h = redo(h);
  expect(h.present).toBe(3);
  h = record(undo(h), 9);
  expect([h.present, h.future]).toEqual([9, []]);
});

it("keeps at most LIMIT steps back, and ignores a change to the same document", () => {
  let h = begin(0);
  for (let i = 1; i <= LIMIT + 5; i++) h = record(h, i);
  expect(h.past.length).toBe(LIMIT);
  expect(record(h, h.present)).toBe(h);
  expect(undo(begin(1))).toEqual(begin(1));
});

it("makes one step of a field's edits while it keeps its mark", () => {
  let h = record(begin("a"), "ab", "f#1");
  h = record(h, "abc", "f#1");
  expect([h.past, h.present]).toEqual([["a"], "abc"]);
  expect(undo(h).present).toBe("a");
});

it("starts a new step for another mark, an unmarked change, or after an undo", () => {
  let h = record(record(begin(0), 1, "x#1"), 2, "y#1");
  expect(h.past).toEqual([0, 1]);
  h = record(record(h, 3), 4);
  expect(h.past).toEqual([0, 1, 2, 3]);
  h = record(undo(record(h, 5, "z#1")), 6, "z#1");
  expect([h.past, h.present]).toEqual([[0, 1, 2, 3, 4], 6]);
});
