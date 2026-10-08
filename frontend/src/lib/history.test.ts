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
