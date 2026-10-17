// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { RUN_STATUS, duration, reasonWords, runId, took } from "./runStatus";

describe("a run's status, in one vocabulary (the runs design §5.5)", () => {
  it("words each status, and says how it looks, as every screen that shows a run does", () => {
    expect(Object.fromEntries(Object.entries(RUN_STATUS).map(([k, v]) => [k, [v.word, v.tone]]))).toEqual({
      queued: ["Queued", "waiting"],
      starting: ["Starting", "waiting"],
      running: ["Running", "running"],
      succeeded: ["Succeeded", "ok"],
      failed: ["Failed", "danger"],
      deadline_exceeded: ["Ran out of time", "danger"],
      cancelled: ["Cancelled", "neutral"],
      dead: ["Couldn't start", "danger"],
      refused: ["Refused", "danger"],
    });
  });

  it("gives a run's duration as a person reads it", () => {
    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:19Z")).toBe("14 s");
    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:45:25Z")).toBe("3 min 20 s");
    expect(duration("2026-10-15T10:00:00Z", "2026-10-15T11:02:00Z")).toBe("1 h 2 min");
    expect(duration("2026-10-15T10:42:05Z", "2026-10-15T10:42:05.300Z")).toBe("under 1 s");
    expect(duration(null, "2026-10-15T10:42:05Z")).toBeNull();
  });

  it("gives a step's time to the tenth of a second while it's short", () => {
    expect(took("2026-10-16T09:41:12Z", "2026-10-16T09:41:12.400Z")).toBe("0.4 s");
    expect(took("2026-10-16T09:41:12Z", "2026-10-16T09:41:13.849Z")).toBe("1.8 s");
    expect(took("2026-10-16T09:41:12Z", "2026-10-16T09:41:42Z")).toBe("30 s");
    expect(took("2026-10-16T09:41:12Z", null)).toBeNull();
  });

  it("names a run by its id's first eight characters", () => {
    expect(runId("7c1e9a40-3b2d-4e5f-9a1b-2c3d4e5f6a7b")).toBe("7c1e9a40");
  });

  it("words why a run didn't start, from its code, and has no words for a code it doesn't know", () => {
    expect(reasonWords("start_throttled")).toBe("Too many runs were starting at once.");
    expect(reasonWords("input_invalid")).toBe("Its input didn't fit the workflow's input.");
    expect(reasonWords("schedule_paused")).toBe("Its schedule was disabled.");
    expect(reasonWords("a_code_from_later")).toBeNull();
    expect(reasonWords(null)).toBeNull();
  });
});
