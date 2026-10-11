// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { TIMING_WORDS, blankWhen, intervalWords, timingOf, timingTitle, whenOf, zones } from "./timing";

const cron = (c: string) => ({ cron: c, every_s: null, offset_s: 0 });
const every = (s: number, offset = 0) => ({ cron: null, every_s: s, offset_s: offset });

describe("a schedule's timing as the form's When", () => {
  it("reads a daily or weekday cron back as its preset, and any other as Custom", () => {
    expect(whenOf(cron("0 7 * * *"))).toMatchObject({ preset: "daily", time: "07:00" });
    expect(whenOf(cron("30 8 * * 1-5"))).toMatchObject({ preset: "weekdays", time: "08:30" });
    expect(whenOf(cron("0 */6 * * 1-5"))).toMatchObject({ preset: "custom", cron: "0 */6 * * 1-5" });
    expect(whenOf(cron("0 9 1 * MON"))).toMatchObject({ preset: "custom" });
  });

  it("reads an interval back as minutes or hours, with where it starts", () => {
    expect(whenOf(every(900, 300))).toMatchObject({ preset: "minutes", every: "15", past: "5" });
    expect(whenOf(every(21_600, 9000))).toMatchObject({ preset: "hours", every: "6", first: "02:30" });
    expect(whenOf(every(5400, 4500))).toMatchObject({ preset: "minutes", every: "90", past: "75" });
  });

  it("keeps an interval no preset writes back exactly, as it is", () => {
    // Not whole minutes, or a first run past the first day: the API takes both (the review of revision 1).
    for (const t of [every(90), every(3600, 30), every(72 * 3600, 51 * 3600)]) {
      expect(whenOf(t).preset).toBe("kept");
      expect(timingOf(whenOf(t))).toEqual({ field: "when", problem: "Choose when it runs." });
    }
  });

  it("gives back exactly the interval it read, for every preset it reads one as", () => {
    for (const t of [every(60), every(900, 300), every(5400, 4500), every(7200, 5400), every(21_600, 9000), every(366 * 86_400, 86_340)]) {
      const w = whenOf(t);
      expect(w.preset).not.toBe("kept");
      expect(timingOf(w)).toEqual({ timing: t });
    }
  });

  it("writes each preset as the API takes it, a cron in the zone or an interval in UTC", () => {
    expect(timingOf({ ...blankWhen("daily"), time: "07:00" })).toEqual({ timing: cron("0 7 * * *") });
    expect(timingOf({ ...blankWhen("weekdays"), time: "09:05" })).toEqual({ timing: cron("5 9 * * 1-5") });
    expect(timingOf({ ...blankWhen("minutes"), every: "15", past: "5" })).toEqual({ timing: every(900, 300) });
    expect(timingOf({ ...blankWhen("hours"), every: "6", first: "02:30" })).toEqual({ timing: every(21_600, 9000) });
    expect(timingOf({ ...blankWhen("custom"), cron: "  0 9   1 * MON " })).toEqual({ timing: cron("0 9 1 * MON") });
  });

  it("round-trips what it writes", () => {
    for (const w of [
      { ...blankWhen("daily"), time: "23:59" },
      { ...blankWhen("weekdays"), time: "00:00" },
      { ...blankWhen("minutes"), every: "20", past: "0" },
      { ...blankWhen("hours"), every: "1", first: "00:45" },
    ]) {
      const made = timingOf(w);
      expect("timing" in made && whenOf(made.timing)).toMatchObject(w);
    }
  });

  it("says which field can't be written yet, and why, before anything is sent", () => {
    expect(timingOf({ ...blankWhen("minutes"), every: "0" })).toEqual({ field: "every", problem: "A whole number of minutes, at least 1." });
    expect(timingOf({ ...blankWhen("minutes"), past: "a" })).toEqual({ field: "past", problem: "A whole number of minutes." });
    expect(timingOf({ ...blankWhen("hours"), every: "1.5" })).toEqual({ field: "every", problem: "A whole number of hours, at least 1." });
    expect(timingOf({ ...blankWhen("hours"), first: "25:00" })).toEqual({ field: "first", problem: "A time, like 02:30." });
    expect(timingOf({ ...blankWhen("daily"), time: "7" })).toEqual({ field: "time", problem: "A time, like 07:00." });
    expect(timingOf({ ...blankWhen("custom"), cron: " " })).toEqual({ field: "cron", problem: "A cron, like 0 9 * * MON." });
  });
});

describe("a timing in words", () => {
  it("titles a schedule as its preset says it, or by its cron", () => {
    expect(timingTitle(cron("0 7 * * *"))).toBe("Every day at 07:00");
    expect(timingTitle(cron("30 8 * * 1-5"))).toBe("Weekdays at 08:30");
    expect(timingTitle(every(900, 300))).toBe("Every 15 minutes");
    expect(timingTitle(every(60))).toBe("Every minute");
    expect(timingTitle(every(3600))).toBe("Every hour");
    expect(timingTitle(every(21_600))).toBe("Every 6 hours");
    expect(timingTitle(cron("0 */6 * * 1-5"))).toBe("At 0 */6 * * 1-5");
    expect(timingTitle(every(90))).toBe("Every 90 seconds");
    expect(timingTitle(every(72 * 3600, 51 * 3600))).toBe("Every 72 hours");
    expect(timingTitle(every(5400, 4500))).toBe("Every 90 minutes");
  });

  it("says when an interval runs, as the ScheduleWhen board does, and that it has no time zone", () => {
    expect(intervalWords({ ...blankWhen("minutes"), every: "15", past: "5" })).toBe(
      "Minutes, at least 1. Runs at :05, :20, :35 and :50 of every hour. An interval is the same everywhere, so it has no time zone.",
    );
    expect(intervalWords({ ...blankWhen("hours"), every: "6", first: "02:30" })).toBe(
      "Runs at 02:30, 08:30, 14:30 and 20:30 UTC, every day. At most every 366 days.",
    );
    expect(intervalWords({ ...blankWhen("hours"), every: "2", first: "03:00" })).toBe(
      "The first run must fall within the first 2 hours of the day: 03:00 is the same as 01:00.",
    );
    expect(intervalWords({ ...blankWhen("minutes"), every: "7", past: "2" })).toBe(
      "Minutes, at least 1. Every 7 minutes, counted from midnight UTC. An interval is the same everywhere, so it has no time zone.",
    );
    expect(intervalWords({ ...blankWhen("minutes"), every: "15", past: "20" })).toBe("Past the hour is less than the interval: 0 to 14.");
    expect(intervalWords({ ...blankWhen("minutes"), every: "x" })).toBeNull();
  });

  it("has words for every timing refusal the API answers", () => {
    const codes = ["cron_fields", "cron_syntax", "cron_range", "cron_day_fields", "timing_missing", "timing_both",
      "interval_too_short", "interval_too_long", "interval_offset", "time_zone_unknown", "catchup_window"];  // prettier-ignore
    expect(Object.keys(TIMING_WORDS).sort()).toEqual([...codes].sort());
    expect(TIMING_WORDS.cron_day_fields).toBe("Choose a day of the month or a day of the week, not both: put * in one of them.");
  });

  it("offers the browser's zone first, then every zone, UTC among them", () => {
    const offered = zones("Asia/Tokyo");
    expect(offered[0]).toBe("Asia/Tokyo");
    expect(offered).toContain("UTC");
    expect(offered).toContain("America/New_York");
    expect(new Set(offered).size).toBe(offered.length);
  });
});
