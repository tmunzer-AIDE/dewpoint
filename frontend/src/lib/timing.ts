// SPDX-License-Identifier: Apache-2.0
// A schedule's timing in words, and as the form's "When" (4c-3b; the mockups' ScheduleForm and ScheduleWhen boards):
// presets over the API's two kinds, a cron in the schedule's own time zone or an interval counted in UTC
// (apps/schedules.py). Only what the form needs to write a request is checked here: the API checks the timing and
// answers each refusal as a field and a code, which `timingWords` says.

/** The form's choices for "When": each writes a cron or an interval; "kept" is an interval none of them says, kept as it
 * is until another is chosen. */
export type Preset = "minutes" | "hours" | "daily" | "weekdays" | "custom" | "kept";

/** What "When" holds, as typed: the form's own state, never sent as is. */
export interface When {
  preset: Preset;
  every: string; // minutes or hours
  past: string; // minutes past the hour, for "minutes"
  first: string; // HH:MM, in UTC, for "hours"
  time: string; // HH:MM, in the time zone, for "daily" and "weekdays"
  cron: string; // for "custom"
}

/** A timing as the API takes it: a cron or an interval, never both. */
export interface Timing {
  cron: string | null;
  every_s: number | null;
  offset_s: number;
}

export const MIN_INTERVAL = 60;
export const MAX_INTERVAL = 366 * 24 * 3600;
export const CATCHUP = [
  { value: 60, label: "1 minute" },
  { value: 600, label: "10 minutes" },
  { value: 3600, label: "1 hour" },
  { value: 21_600, label: "6 hours" },
  { value: 86_400, label: "24 hours" },
] as const;

const pad = (n: number) => String(n).padStart(2, "0");
const clock = (seconds: number) => `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))}`;
const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;
const WHOLE = /^[1-9]\d{0,6}$/;
const DAILY = /^([0-5]?\d) ([01]?\d|2[0-3]) \* \* (\*|1-5)$/;

/** A time typed as HH:MM, as seconds into the day; null when it isn't one. */
export function secondsOf(time: string): number | null {
  const m = TIME.exec(time.trim());
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 : null;
}

const whole = (text: string): number | null => (WHOLE.test(text.trim()) ? Number(text.trim()) : null);
const natural = (text: string): number | null => (/^\d{1,7}$/.test(text.trim()) ? Number(text.trim()) : null);

/** A blank "When" of a preset, as a new schedule starts. */
export const blankWhen = (preset: Preset = "daily"): When => ({ preset, every: "15", past: "0", first: "00:00", time: "07:00", cron: "" });

/** A schedule's timing as the form shows it, read back exactly: a cron no preset says opens as Custom; an interval no
 * preset says (not whole minutes, or a first run past the first day) opens as kept, as it is (the review of revision 1). */
export function whenOf(t: Timing): When {
  const blank = blankWhen();
  if (t.cron !== null) {
    const m = DAILY.exec(t.cron.trim());
    if (!m) return { ...blank, preset: "custom", cron: t.cron };
    return { ...blank, preset: m[3] === "*" ? "daily" : "weekdays", time: `${pad(Number(m[2]))}:${pad(Number(m[1]))}` };
  }
  const every = t.every_s ?? 0;
  if (t.offset_s % 60 !== 0) return { ...blank, preset: "kept" };
  if (every % 3600 === 0) return t.offset_s < 86_400 ? { ...blank, preset: "hours", every: String(every / 3600), first: clock(t.offset_s) } : { ...blank, preset: "kept" };
  if (every % 60 === 0) return { ...blank, preset: "minutes", every: String(every / 60), past: String(t.offset_s / 60) };
  return { ...blank, preset: "kept" };
}

/** What a "When" asks for, or why it can't be written yet: a field of its own and the words for it. */
export function timingOf(w: When): { timing: Timing } | { field: keyof When | "when"; problem: string } {
  switch (w.preset) {
    case "minutes":
    case "hours": {
      const unit = w.preset === "minutes" ? 60 : 3600;
      const n = whole(w.every);
      if (n === null) return { field: "every", problem: w.preset === "minutes" ? "A whole number of minutes, at least 1." : "A whole number of hours, at least 1." };
      if (w.preset === "minutes") {
        const past = w.past.trim() === "" ? 0 : natural(w.past);
        if (past === null) return { field: "past", problem: "A whole number of minutes." };
        return { timing: { cron: null, every_s: n * unit, offset_s: past * 60 } };
      }
      const first = secondsOf(w.first);
      if (first === null) return { field: "first", problem: "A time, like 02:30." };
      return { timing: { cron: null, every_s: n * unit, offset_s: first } };
    }
    case "daily":
    case "weekdays": {
      const at = secondsOf(w.time);
      if (at === null) return { field: "time", problem: "A time, like 07:00." };
      const days = w.preset === "daily" ? "*" : "1-5";
      return { timing: { cron: `${(at % 3600) / 60} ${Math.floor(at / 3600)} * * ${days}`, every_s: null, offset_s: 0 } };
    }
    case "custom":
      if (w.cron.trim() === "") return { field: "cron", problem: "A cron, like 0 9 * * MON." };
      return { timing: { cron: w.cron.trim().split(/\s+/).join(" "), every_s: null, offset_s: 0 } };
    case "kept": // never written: the form sends no timing while it's kept
      return { field: "when", problem: TIMING_WORDS.timing_missing! };
  }
}

/** A schedule's timing, as its title: "Every day at 07:00", "Every 15 minutes", "Every 90 seconds", or a cron no preset
 * says as itself, "At 0 9 1 * *". An interval is titled in its largest whole unit. */
export function timingTitle(t: Timing): string {
  if (t.cron === null) {
    const s = t.every_s ?? 0;
    if (s % 3600 === 0) return s === 3600 ? "Every hour" : `Every ${s / 3600} hours`;
    if (s % 60 === 0) return s === 60 ? "Every minute" : `Every ${s / 60} minutes`;
    return `Every ${s} seconds`;
  }
  const w = whenOf(t);
  if (w.preset === "daily") return `Every day at ${w.time}`;
  if (w.preset === "weekdays") return `Weekdays at ${w.time}`;
  return `At ${t.cron}`;
}

const list = (items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)!}`);

/** When an interval runs, in words, under its fields: the times it makes when they're few, else its start. An
 * interval is counted in UTC, the same everywhere: it has no time zone. Null while it can't be said. */
export function intervalWords(w: When): string | null {
  const n = whole(w.every);
  if (n === null) return null;
  if (w.preset === "minutes") {
    const past = w.past.trim() === "" ? 0 : natural(w.past);
    if (past === null) return null;
    if (past >= n) return `Past the hour is less than the interval: ${n === 1 ? "0" : `0 to ${n - 1}`}.`;
    const none = "An interval is the same everywhere, so it has no time zone.";
    if (60 % n !== 0 || 60 / n > 6) return `Minutes, at least 1. Every ${n} minutes, counted from midnight UTC. ${none}`;
    const times = Array.from({ length: 60 / n }, (_, i) => `:${pad(past + i * n)}`);
    return `Minutes, at least 1. Runs at ${list(times)} of every hour. ${none}`;
  }
  if (w.preset === "hours") {
    const first = secondsOf(w.first);
    if (first === null) return null;
    if (first >= n * 3600) {
      const same = clock(first % (n * 3600));
      return `The first run must fall within the first ${n === 1 ? "hour" : `${n} hours`} of the day: ${w.first} is the same as ${same}.`;
    }
    if (24 % n !== 0 || 24 / n > 6) return `Every ${n} hours from ${w.first} UTC, counted from midnight. At most every 366 days.`;
    const times = Array.from({ length: 24 / n }, (_, i) => clock(first + i * n * 3600));
    return `Runs at ${list(times)} UTC, every day. At most every 366 days.`;
  }
  return null;
}

/** The API's refusals of a timing (apps/schedules.py's TIMING_CODES), in words, by the field the form shows them at. */
export const TIMING_WORDS: Record<string, string> = {
  cron_fields: "Five fields: minute, hour, day of the month, month, day of the week.",
  cron_syntax: "Each field is a number, a range, a list or a step, like 5, 1-5, 1,15 or */10; months and days may be names, like JAN or MON.",
  cron_range: "A value is outside its field (minutes 0–59, hours 0–23, days 1–31, months 1–12, days of the week 0–7), a range runs backwards, or a step is 0.",
  cron_day_fields: "Choose a day of the month or a day of the week, not both: put * in one of them.",
  timing_missing: "Choose when it runs.",
  timing_both: "A schedule runs on a cron or an interval, not both.",
  interval_too_short: "At least every minute.",
  interval_too_long: "At most every 366 days.",
  interval_offset: "It must fall within the interval, from its start.",
  time_zone_unknown: "Not a time zone this server knows: choose one from the list.",
  catchup_window: "From 1 minute to 24 hours.",
};

/** The time zones offered, the browser's first; the API holds them to its own list (`time_zone_unknown`). */
export function zones(browser: string = Intl.DateTimeFormat().resolvedOptions().timeZone): string[] {
  const all = new Set(Intl.supportedValuesOf("timeZone"));
  all.add("UTC");
  return [browser, ...[...all].filter((z) => z !== browser).sort()];
}
