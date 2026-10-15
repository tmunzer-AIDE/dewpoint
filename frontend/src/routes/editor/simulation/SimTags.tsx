// SPDX-License-Identifier: Apache-2.0
// A simulated step's tags beside its card (4d-1c; the simulation design §7.3; the ResultCanvas and Narrow boards):
// beside it, under it at narrow widths, never on it, so the card and its problem and "may not run" badges stay as they
// are. Where another card is beside it, under it (`place`); under, they take one line, cut short, every word still read
// out (the review's 1). Each tag is drawn as what it is: a status, values a person gave (slate outline), a fixture (hatched slate), an
// evaluation, an absence (dashed), a note; the words carry it, the look only repeats them (§7.4).
import type { SimTag, SimTagKind } from "./results";

const LOOK: Record<SimTagKind, string> = {
  ok: "rounded-md border border-ok bg-surface px-1.5 text-ok",
  fail: "rounded-md border border-danger bg-surface px-1.5 text-danger",
  status: "rounded-md border border-line-strong bg-surface px-1.5 text-muted",
  given: "rounded-sm border border-sim bg-surface px-1.5 text-sim",
  fixture: "hatch-sim rounded-sm border border-sim bg-sim-bg px-1.5 text-sim",
  evaluated: "rounded-sm border border-line-strong bg-surface px-1.5 text-muted",
  absent: "rounded-sm border border-dashed border-line-strong bg-surface px-1.5 text-muted",
  note: "bg-surface text-muted",
};

const PLACE = {
  beside:
    "top-0 left-full ml-2 flex w-[240px] flex-wrap content-start gap-1 @max-3xl:top-full @max-3xl:left-0 @max-3xl:mt-[56px] " +
    "@max-3xl:ml-0 @max-3xl:block @max-3xl:w-[260px] @max-3xl:truncate",
  under: "top-full left-0 mt-[56px] block w-[260px] truncate",
} as const;

export function SimTags({ label, tags, place = "beside" }: { label: string; tags: SimTag[]; place?: keyof typeof PLACE }) {
  if (tags.length === 0) return null;
  return (
    <ul aria-label={`${label}: simulated result`} className={`pointer-events-none absolute text-meta ${PLACE[place]}`}>
      {tags.map((t, i) => (
        // Inline, so a line cut short ends in "…"; a flex item when beside.
        <li key={i} className={`inline leading-[18px] whitespace-nowrap ${place === "under" ? "me-1" : "@max-3xl:me-1"} ${LOOK[t.kind]}`}>{t.text}</li>
      ))}
    </ul>
  );
}

/** The same tags in a line of text: the Simulation panel's steps (§7.5). */
export function InlineTags({ tags }: { tags: SimTag[] }) {
  return tags.map((t, i) => (
    <span key={i} className={`text-meta leading-[18px] whitespace-nowrap ${LOOK[t.kind]}`}>{t.text}</span>
  ));
}
