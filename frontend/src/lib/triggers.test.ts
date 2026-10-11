// SPDX-License-Identifier: Apache-2.0
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  attentionWords, bindingLine, filterWords, missesNote, parseValue, scheduleMeta, scheduleNote, startFormQuery, startLabel,
  possessive, startSummary, topicOf, triggerColumn, valueText,
} from "./triggers";  // prettier-ignore
import { MIST, SCHEDULE } from "../test/triggers";

afterEach(() => vi.restoreAllMocks());

describe("a schedule in words", () => {
  it("says its zone where one applies, its mode, off, custom and synced, as the Schedules board does", () => {
    expect(scheduleMeta(SCHEDULE)).toBe("Europe/Paris · live · synced");
    expect(scheduleMeta({ ...SCHEDULE, cron: null, every_s: 900, mode: "simulate", enabled: false })).toBe("simulated: nothing is sent · off · synced");
    expect(scheduleMeta({ ...SCHEDULE, cron: "0 */6 * * 1-5", time_zone: "UTC" })).toBe("UTC · live · custom · synced");
    expect(scheduleMeta({ ...SCHEDULE, generation: 3 })).toBe("Europe/Paris · live");
  });

  it("says what its sync proves: never that one not yet synced isn't running, unless nothing ever unpaused it", () => {
    expect(scheduleNote(SCHEDULE)).toBeNull();
    expect(scheduleNote({ ...SCHEDULE, generation: 1, synced_generation: 0 })).toBe("Saved; sync not yet confirmed: it may already fire.");
    expect(scheduleNote({ ...SCHEDULE, generation: 1, synced_generation: 0, never_unpaused: true })).toBe(
      "Saved; not running yet: the scheduler takes it on its own, usually within seconds.",
    );
    expect(scheduleNote({ ...SCHEDULE, generation: 3 })).toBe("Saved; sync not yet confirmed: until it is, the previous time or the new one may fire.");
  });

  it("says a failed sync pauses nothing: the previous time may still fire", () => {
    const failed = { ...SCHEDULE, sync_error: "invalid_spec", sync_error_at: "2026-10-11T08:01:00Z" };
    expect(scheduleNote({ ...failed, generation: 3 })).toMatch(/^Sync failed: the scheduler refused this change\. Its previous time may still fire/);
    expect(scheduleNote({ ...failed, generation: 1, synced_generation: 0 })).toMatch(/its sync was never confirmed, so it may already fire/);
    expect(scheduleNote({ ...failed, generation: 1, synced_generation: 0, never_unpaused: true })).toMatch(/so it isn't running yet/);
  });

  it("says the firings it missed, and that some may be missed still", () => {
    expect(missesNote(SCHEDULE)).toBeNull();
    const missed = { ...SCHEDULE, misses: 3, misses_read_at: "2026-10-11T14:05:00Z", accounting_complete: false };
    expect(missesNote(missed, "UTC")).toBe("3 firings missed, counted at 14:05. Some may be missed still, not yet counted.");
    expect(missesNote({ ...missed, misses: 1, accounting_complete: true }, "UTC")).toBe("1 firing missed, counted at 14:05.");
    expect(missesNote({ ...SCHEDULE, accounting_complete: false })).toBe("Some firings may be missed, not yet counted.");
  });
});

describe("what starts a workflow, in words", () => {
  it("sums it up on the start card, its name starting with what it shows", () => {
    expect(startSummary({ csv: false, schedules: 0, webhooks: 0 })).toBe("By hand");
    expect(startSummary({ csv: false, schedules: 2, webhooks: 0 })).toBe("By hand · 2 schedules");
    expect(startSummary({ csv: false, schedules: 1, webhooks: 1 })).toBe("By hand · 1 schedule · 1 webhook");
    expect(startSummary({ csv: true, schedules: 0, webhooks: 0 })).toBe("By hand, with a CSV file");
    expect(startLabel("By hand · 2 schedules")).toBe("Start: by hand, 2 schedules. Open its triggers");
  });

  it("names what else starts it in the list's Trigger column, as the WorkflowsList board does", () => {
    const t = (schedules: number, webhook_bindings: number, csv = false) => ({ schedules, schedules_enabled: schedules, webhook_bindings, csv });
    expect(triggerColumn(t(0, 1))).toBe("Webhook");
    expect(triggerColumn(t(2, 1))).toBe("2 schedules · 1 webhook");
    expect(triggerColumn(t(1, 0))).toBe("Schedule");
    expect(triggerColumn(t(0, 0, true))).toBe("CSV file");
    expect(triggerColumn(t(0, 0))).toBe("By hand");
  });

  it("says why a workflow needs attention", () => {
    expect(attentionWords([])).toBeNull();
    expect(attentionWords(["last_run_failed"])).toBe("Needs attention: its last run failed.");
    expect(attentionWords(["schedule_sync_failed"])).toBe("Needs attention: a schedule couldn't be synced.");
    expect(attentionWords(["last_run_failed", "not_executable", "schedule_sync_failed"])).toBe(
      "Needs attention: its last run failed, its active version can't run and a schedule couldn't be synced.",
    );
  });
});

describe("a webhook binding in words", () => {
  const binding = (trigger: string | null, filter: { pointer: string; value: string | number | boolean | null }[]) => ({ endpoint: { trigger }, filter });

  it("names a Mist binding's topic, and another sender's filter", () => {
    expect(bindingLine(binding("mist.webhook", [{ pointer: "/topic", value: "device-events" }]), [MIST])).toBe("Mist · topic device-events");
    expect(bindingLine(binding(null, [{ pointer: "/type", value: "incident" }, { pointer: "/priority", value: 1 }]), [MIST])).toBe(
      "Another sender · /type is incident and /priority is 1",
    );
    expect(bindingLine(binding(null, []), [MIST])).toBe("Another sender · every event");
  });

  it("says when an endpoint's trigger is no longer declared, and a Mist filter that isn't a topic", () => {
    expect(bindingLine(binding("old.hook", []), [MIST])).toBe("An unknown sender (old.hook) · every event");
    expect(bindingLine(binding("mist.webhook", [{ pointer: "/topic", value: "nope" }]), [MIST])).toBe("Mist · /topic is nope");
    expect(topicOf([{ pointer: "/topic", value: "alarms" }], MIST)).toBe("alarms");
    expect(topicOf([{ pointer: "/topic", value: "alarms" }, { pointer: "/x", value: 1 }], MIST)).toBeNull();
  });

  it("quotes text that would read as a number, a yes or no, or null", () => {
    expect(filterWords([{ pointer: "/a", value: "1" }, { pointer: "/b", value: true }, { pointer: "/c", value: null }])).toBe(
      '/a is "1" and /b is true and /c is null',
    );
  });

  it("reads a typed value as written: whole numbers, true, false and null as such, quoted text as text", () => {
    expect(parseValue("1")).toEqual({ value: 1 });
    expect(parseValue(" -42 ")).toEqual({ value: -42 });
    expect(parseValue("true")).toEqual({ value: true });
    expect(parseValue("null")).toEqual({ value: null });
    expect(parseValue('"1"')).toEqual({ value: "1" });
    expect(parseValue("1.5")).toEqual({ value: "1.5" });
    expect(parseValue("incident")).toEqual({ value: "incident" });
    expect(parseValue("9007199254740993")).toEqual({ problem: "A whole number this large can't be kept exactly: put it in quotes to match it as text." });
    expect(parseValue("x".repeat(1025))).toEqual({ problem: "At most 1,024 characters." });
    for (const v of [1, "1", true, "true", null, "incident"] as const) expect(parseValue(valueText(v))).toEqual({ value: v });
  });

  it("shows every value so that reading it again gives it back exactly: spaces, quotes and escapes kept", () => {
    // The API keeps text as sent, and matches it so (the review of revision 1).
    const values = [" HQ ", "HQ ", '"quoted"', '"', 'say "hi"', "", "x\\y", "tab\there", "line\nbreak", "-0", "1e3", 'a"b"', 42, -7, 0, true, false, null] as const;
    for (const v of values) expect(parseValue(valueText(v)), JSON.stringify(v)).toEqual({ value: v });
    expect(valueText(" HQ ")).toBe('" HQ "');
    expect(valueText('"quoted"')).toBe('"\\"quoted\\""');
    expect(valueText("HQ")).toBe("HQ");
    expect(valueText("")).toBe('""');
    expect(filterWords([{ pointer: "/site", value: " HQ " }])).toBe('/site is " HQ "');
  });

  it("shows text with a line break as JSON text: a one-line field would drop the break", () => {
    // The final review: "a\nb" made through the API was shown raw, and saved back as "ab".
    for (const v of ["a\nb", "a\rb", "a\r\nb"]) {
      expect(valueText(v)).toBe(JSON.stringify(v));
      expect(parseValue(valueText(v))).toEqual({ value: v });
    }
  });

  it("names a binding's sender by its key while the trigger types aren't known, never as unknown", () => {
    // The final review: "not loaded" read as "no plugin declares it any more".
    expect(bindingLine({ endpoint: { trigger: "mist.webhook" }, filter: [{ pointer: "/topic", value: "alarms" }] }, undefined)).toBe("mist.webhook · /topic is alarms");
    expect(bindingLine({ endpoint: { trigger: "gone.webhook" }, filter: [] }, [MIST])).toBe("An unknown sender (gone.webhook) · every event");
  });

  it("reads text in quotes as JSON text, and says so when it isn't", () => {
    expect(parseValue('" HQ "')).toEqual({ value: " HQ " });
    expect(parseValue('"a\\"b"')).toEqual({ value: 'a"b' });
    expect(parseValue('"a"b"')).toEqual({ problem: 'Text in quotes is read as JSON text: write \\" for a quote inside it.' });
  });
});

it("reads the start form as null while nothing is published", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: "not_active" }), { status: 409 }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  expect(await qc.query(startFormQuery("t1", "w1"))).toBeNull();
});

it("says a name's possessive as the boards do", () => {
  expect(possessive("device-events")).toBe("device-events'");
  expect(possessive("client-join")).toBe("client-join's");
});
