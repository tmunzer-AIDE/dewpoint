// SPDX-License-Identifier: Apache-2.0
// What started a run, in words (editor 4e-1; the runs design §5.2): its kind, then the person who asked (by hand), the
// schedule's timing, the endpoint's name, or the run a re-run repeats. A run from before its request recorded these
// says what it can.
import type { ReactNode } from "react";
import type { RunItem } from "../../lib/runs";
import { runId } from "../../lib/runStatus";
import { timingTitle } from "../../lib/timing";

const KIND: Record<NonNullable<RunItem["trigger"]>["source"], string> = {
  manual: "By hand",
  rerun: "Re-run",
  schedule: "Schedule",
  webhook: "Webhook",
  dev: "Development",
};

/** Its kind ("By hand"), and what says more about it, when known: drawn (`detail`, a re-run's id in mono) and in
 * plain words (`words`, for a name). */
export function triggerOf(run: RunItem): { kind: string; detail: ReactNode; words: string | null } {
  const t = run.trigger;
  if (t === null) return { kind: "—", detail: null, words: null };
  if (t.source === "rerun" && t.rerun_of) {
    return { kind: KIND.rerun, detail: <>of <span className="font-mono">{runId(t.rerun_of)}</span></>, words: `of ${runId(t.rerun_of)}` };
  }
  const words =
    t.source === "manual" ? run.started_by
    : t.source === "schedule" ? t.schedule && timingTitle(t.schedule)
    : t.source === "webhook" ? t.endpoint
    : null;  // prettier-ignore
  // A source from a later server is shown by its code; an own-property check, never the prototype's names.
  const kind = Object.hasOwn(KIND, t.source) ? KIND[t.source] : String(t.source);
  return { kind, detail: words ?? null, words: words ?? null };
}

/** The same in a sentence: "webhook, Mist events", "schedule, weekdays at 06:00". */
export function triggerWords(run: RunItem): string {
  const { kind, words } = triggerOf(run);
  const said = words && run.trigger?.source === "schedule" ? words.charAt(0).toLowerCase() + words.slice(1) : words;
  return `${kind.toLowerCase()}${said ? `, ${said}` : ""}`;
}
