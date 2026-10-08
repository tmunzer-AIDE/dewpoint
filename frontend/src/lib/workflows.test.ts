// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { canEdit, canPublish, notPortable, since } from "./workflows";

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

it("says why a workflow isn't portable, naming its steps when it can", () => {
  const problems = [
    { reason: "unknown_type", binding: null, node: "n1", field: null },
    { reason: "unexpected_value", binding: null, node: "n2", field: "/connection" },
    { reason: "unexpected_value", binding: null, node: null, field: "/settings/failure_handler" },
  ];
  expect(notPortable(problems)).toBe(
    "it has steps of a type this server doesn't know, and something other than an id where a connection or workflow goes",
  );
  expect(notPortable(problems, (id) => ({ n1: "odd", n2: "call" })[id] ?? id)).toBe(
    "it has steps of a type this server doesn't know (odd), and something other than an id where a connection or workflow goes (call, the failure handler)",
  );
});

it("says when a workflow holds a sensitive value written into it, never the value (ledger M25)", () => {
  const problems = [{ reason: "sensitive_literal", binding: null, node: "n1", field: "/token" }];
  expect(notPortable(problems)).toBe("it has a sensitive value written into a step");
  expect(notPortable(problems, () => "send")).toBe("it has a sensitive value written into a step (send)");
});
