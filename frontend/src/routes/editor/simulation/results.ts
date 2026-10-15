// SPDX-License-Identifier: Apache-2.0
// A simulated step's result, as tags beside its card (4d-1c; the simulation design §7.3, §7.4; the ResultCanvas and
// Running boards), from the server's per-step summary, never a partial page. A step that ran once shows its final
// attempt; a loop's step totals its instances, one per opened iteration, skipped ones included, its ports apart; a
// step with none says why, in the server's tag. Always words: the colour and the hatch only repeat them.
import type { Origin, StepSummary } from "../../../lib/simulations";

/** What a tag is: a status (ok, failed or other), values a person gave, a plugin's fixture, an evaluation, an absence,
 * or a note (an attempt, a loop's iterations). */
export type SimTagKind = "ok" | "fail" | "status" | "given" | "fixture" | "evaluated" | "absent" | "note";
export interface SimTag {
  text: string;
  kind: SimTagKind;
}

/** §7.4's tags, in the server's code and the words the editor shows. */
export const ORIGIN: Record<Origin | "input" | "seeded", string> = {
  input: "input",
  seeded: "seeded",
  evaluated: "evaluated",
  evaluated_not_waited: "evaluated · not waited",
  fixture_not_sent: "fixture · not sent",
  skipped: "skipped",
  not_started: "not started",
  cancelled: "cancelled",
  didnt_run: "didn't run",
  not_recorded: "not recorded",
  not_reached_yet: "not reached yet",
};
const ORIGIN_KIND: Record<Origin, SimTagKind> = {
  evaluated: "evaluated",
  evaluated_not_waited: "evaluated",
  fixture_not_sent: "fixture",
  skipped: "absent",
  not_started: "absent",
  cancelled: "status",
  didnt_run: "absent",
  not_recorded: "absent",
  not_reached_yet: "absent",
};

/** Where a step's data came from, as its tag. */
export const originTag = (origin: Origin): SimTag => ({ text: ORIGIN[origin], kind: ORIGIN_KIND[origin] });

const ORDER = ["succeeded", "failed", "cancelled", "skipped", "not_started", "running"];
const said = (status: string) => status.replace("_", " ");
const statusKind = (status: string): SimTagKind => (status === "succeeded" ? "ok" : status === "failed" ? "fail" : "status");
export const field = (v: unknown, key: string): unknown => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>)[key] : undefined);

export const words = (tags: SimTag[]) => tags.map((t) => t.text);

/** A step's tags. `maxAttempts`: its own, or its type's (an attempt is said "of" it); `ended`: whether the
 * simulation has (while it runs, a loop's step says what it has so far). */
export function tagsOf(s: StepSummary, { maxAttempts, ended }: { maxAttempts: number | null; ended: boolean }): SimTag[] {
  if (s.instances === 0) return [{ text: ORIGIN[s.origin], kind: ORIGIN_KIND[s.origin] }];
  const loop = s.type.startsWith("flow.loop@");
  if (s.instances === 1) {
    const status = typeof field(s.final, "status") === "string" ? (field(s.final, "status") as string) : (Object.keys(s.statuses)[0] ?? "running");
    if (status === "skipped" || status === "not_started" || status === "cancelled") return [{ text: said(status), kind: ORIGIN_KIND[status] }];
    const tags: SimTag[] = [{ text: said(status), kind: statusKind(status) }];
    const attempt = field(s.final, "attempt");
    if (typeof attempt === "number" && attempt > 1 && maxAttempts) tags.push({ text: `attempt ${attempt} of ${maxAttempts}`, kind: "note" });
    if (loop) {
      const count = field(field(s.final, "output"), "count");
      const items = field(field(s.final, "input"), "items");
      if (typeof count === "number") tags.push({ text: `${count} ${count === 1 ? "iteration" : "iterations"}`, kind: "note" });
      else if (!ended && Array.isArray(items)) tags.push({ text: `${items.length} ${items.length === 1 ? "item" : "items"}`, kind: "note" });
      return tags;
    }
    const port = field(field(s.final, "effect"), "port");
    const origin = ORIGIN[s.origin] + (typeof port === "string" && s.origin === "evaluated" ? ` · → ${port}` : "");
    return [...tags, { text: origin, kind: ORIGIN_KIND[s.origin] }];
  }
  const counts = ORDER.filter((k) => (s.statuses[k] ?? 0) > 0).map((k) => `${s.statuses[k]} ${said(k)}`).join(" · ");
  const total = `${s.instances} instances: ${counts}`;
  return [
    { text: ended ? total : `So far, ${total}`, kind: "status" },
    ...(loop ? [] : [{ text: ORIGIN[s.origin], kind: ORIGIN_KIND[s.origin] }]),
    ...Object.entries(s.ports).map(([port, n]): SimTag => ({ text: `→ ${port} ×${n}`, kind: "evaluated" })),
  ];
}
