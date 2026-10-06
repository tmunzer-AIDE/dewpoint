// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { canEdit, canPublish, since } from "./workflows";

it("lets editors and above edit and publish, as the API's role sets do", () => {
  for (const role of ["owner", "admin", "editor"]) expect([canEdit(role), canPublish(role)]).toEqual([true, true]);
  for (const role of ["operator", "viewer", null, undefined]) expect([canEdit(role), canPublish(role)]).toEqual([false, false]);
});

it("says how long ago, in words, then as a date", () => {
  const now = Date.parse("2026-10-06T12:00:00Z");
  expect(since("2026-10-06T11:59:40Z", now)).toBe("just now");
  expect(since("2026-10-06T11:48:00Z", now)).toBe("12 min ago");
  expect(since("2026-10-06T09:00:00Z", now)).toBe("3 h ago");
  expect(since("2026-10-05T09:00:00Z", now)).toBe("yesterday");
  expect(since("2026-09-30T09:00:00Z", now)).toMatch(/30 Sept?/);
});
