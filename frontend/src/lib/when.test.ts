// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { when, whenFull } from "./when";

// Instants built from the person's own clock: what they read doesn't depend on the zone the tests run in.
const local = (day: number, h: number, m: number, s: number) => new Date(2026, 9, day, h, m, s).toISOString();
const NOW = new Date(2026, 9, 16, 12, 0, 0).getTime();

it("says when, in the person's own zone: today, yesterday, else the date, each to the second (the owner's answer 8)", () => {
  expect(when(local(16, 10, 2, 9), NOW)).toBe("today 10:02:09");
  expect(when(local(15, 2, 0, 1), NOW)).toBe("yesterday 02:00:01");
  expect(when(local(14, 17, 40, 2), NOW)).toBe("14 Oct 17:40:02");
  expect(when(local(16, 0, 0, 0), NOW)).toBe("today 00:00:00");
});

it("gives the full date and time for the hover", () => {
  expect(whenFull(local(16, 10, 2, 9))).toMatch(/^Friday, 16 October 2026 at 10:02:09 \S+/);
});
