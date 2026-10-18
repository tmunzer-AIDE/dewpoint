// SPDX-License-Identifier: Apache-2.0
// A step's result, as tags beside its card (4d-1c; the simulation design §7.3, §7.4; the ResultCanvas and Running
// boards), from the server's per-step summary, never a partial page. A step that ran once shows its final attempt; a
// loop's step totals its instances, one per opened iteration, skipped ones included, its ports apart; a step with none
// says why, in the server's tag. Always words: the colour and the hatch only repeat them. A run's page (editor 4e-1;
// the runs design §5.3, §5.5) says the same of any run: a live step's origin (sent, may have been sent; a control step
// says none, its port alone), how long an action took, and a failure's code.
import { CARD } from "../../../lib/layout";
import type { RunOrigin } from "../../../lib/runs";
import { took } from "../../../lib/runStatus";

type Origin = NonNullable<RunOrigin>;

/** What a tag is: a status (ok, failed or other), values a person gave, a plugin's fixture, an evaluation, an absence,
 * a note (an attempt, a loop's iterations, a time), a live step's request sent or maybe sent, or an error's code. */
export type SimTagKind = "ok" | "fail" | "status" | "given" | "fixture" | "evaluated" | "absent" | "note" | "sent" | "maybe" | "code";
export interface SimTag {
  text: string;
  kind: SimTagKind;
}

/** §7.4's tags, in the server's code and the words the editor shows. */
export const ORIGIN: Record<Origin | "input" | "seeded", string> = {
  sent: "sent",
  may_have_been_sent: "may have been sent",
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
  sent: "sent",
  may_have_been_sent: "maybe",
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
const strOf = (v: unknown) => (typeof v === "string" ? v : null);

export const words = (tags: SimTag[]) => tags.map((t) => t.text);

/** The box a step's tags take beside its card (SimTags): 8 px off its right edge, 240 px wide, the card's height. */
const BESIDE = { gap: 8, width: 240 };
type At = { x: number; y: number };

/** Whether a card's tags fit beside it (§7.3): no other card (`others`, by their top-left corners) in that box. Else
 * they go under it, on one line (the review's 1; the owner's choice, "beside, else under"). */
export function tagsFitBeside(at: At, others: At[]): boolean {
  const box = { x: at.x + CARD.width + BESIDE.gap, y: at.y, width: BESIDE.width, height: CARD.height };
  return !others.some((o) => o.x < box.x + box.width && box.x < o.x + CARD.width && o.y < box.y + box.height && box.y < o.y + CARD.height);
}

/** A step's summary, a simulation's or any run's: a live one's origin may be none. */
export interface Summary {
  type: string;
  origin: RunOrigin;
  instances: number;
  statuses: Record<string, number>;
  ports: Record<string, number>;
  final?: unknown;
}

const originTags = (origin: RunOrigin): SimTag[] => (origin === null ? [] : [originTag(origin)]);

/** A step's tags. `maxAttempts`: its own, or its type's (an attempt is said "of" it); `ended`: whether the run has
 * (while it runs, a loop's step says what it has so far). `run`, on a run's page: whether the step is an action, whose
 * time is said; a control step's is the engine's own. A failure says its code there, in place of its time. */
export function tagsOf(s: Summary, { maxAttempts, ended, run }: { maxAttempts: number | null; ended: boolean; run?: { action: boolean } }): SimTag[] {
  if (s.instances === 0) return originTags(s.origin);
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
    if (s.origin === "evaluated" && typeof port === "string") tags.push({ text: `${ORIGIN.evaluated} · → ${port}`, kind: "evaluated" });
    else if (s.origin === null && typeof port === "string") tags.push({ text: `→ ${port}`, kind: "evaluated" });
    else tags.push(...originTags(s.origin));
    if (!run) return tags;
    const code = field(field(s.final, "error"), "code");
    const time = run.action ? took(strOf(field(s.final, "started_at")), strOf(field(s.final, "ended_at"))) : null;
    if (status === "failed" && typeof code === "string") tags.push({ text: code, kind: "code" });
    else if (time !== null) tags.push({ text: time, kind: "note" });
    return tags;
  }
  const counts = ORDER.filter((k) => (s.statuses[k] ?? 0) > 0).map((k) => `${s.statuses[k]} ${said(k)}`).join(" · ");
  const total = `${s.instances} instances: ${counts}`;
  return [
    { text: ended ? total : `So far, ${total}`, kind: "status" },
    ...(loop ? [] : originTags(s.origin)),
    ...Object.entries(s.ports).map(([port, n]): SimTag => ({ text: `→ ${port} ×${n}`, kind: "evaluated" })),
  ];
}
