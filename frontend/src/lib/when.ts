// SPDX-License-Identifier: Apache-2.0
// When a run happened, as the person reads it (editor 4e-1; the owner's answer 8): in their own zone, to the second,
// "today" and "yesterday" by their calendar, else the date; the full date and zone on hover.
const TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
const FULL = new Intl.DateTimeFormat("en-GB", { dateStyle: "full", timeStyle: "long" });

const dayOf = (t: Date) => new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();

/** "today 10:02:09", "yesterday 02:00:01", else "14 Oct 17:40:02". */
export function when(iso: string, now: number = Date.now()): string {
  const t = new Date(iso);
  const days = Math.round((dayOf(new Date(now)) - dayOf(t)) / 86_400_000);
  const day = days === 0 ? "today" : days === 1 ? "yesterday" : DATE.format(t);
  return `${day} ${TIME.format(t)}`;
}

/** "Friday 16 October 2026 at 10:02:09 CEST": the full date, the time and the zone. */
export const whenFull = (iso: string) => FULL.format(new Date(iso));
