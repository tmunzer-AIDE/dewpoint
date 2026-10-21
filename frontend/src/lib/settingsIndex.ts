// SPDX-License-Identifier: Apache-2.0
// Find a setting (4f-2, the Mist step design §5.4): every setting a body offers, top-level and nested, through its
// objects, a map's entries and a list's items, each with its path of titles, its raw path and its description, found
// by every word typed. Built once per body and kind: site settings has some 1,700 (R6 §9).
import { entryOf, itemOf, offeredOf, type FieldSpec } from "./schemaForm";

/** One step down from the body: a setting, a map's entry or a list's item. */
export type Step = { kind: "setting" | "entry" | "item"; name: string };
export interface Setting {
  steps: Step[]; // from the body down; an entry or an item is any one
  spec: FieldSpec; // at an example place (an entry named "*", the first item)
  titles: string[]; // "Rogue", "Min rogue RSSI"; through a map "Port usages", "an entry", "Mode"
  raw: string; // "rogue.min_rogue_rssi"; through a map "port_usages.*.mode", a list "networks[].name"
  description: string;
}

export const MAX_SHOWN = 50;

const cache = new WeakMap<object, Map<string, Setting[]>>();

/** Every setting `body` (or a branch of it) offers, the kind's left out, top-level first in the schema's order. */
export function settingsOf(body: FieldSpec, kind: string | null = null): Setting[] {
  const key = `${body.pointer}|${body.label}|${kind ?? ""}`;
  const known = cache.get(body.type)?.get(key);
  if (known) return known;
  const out: Setting[] = [];
  const walk = (specs: FieldSpec[], steps: Step[], titles: string[], raw: string) => {
    for (const spec of specs) {
      const here = { steps: [...steps, { kind: "setting" as const, name: spec.name }], titles: [...titles, spec.label], raw: raw === "" ? spec.name : `${raw}.${spec.name}` };
      out.push({ ...here, spec, description: typeof spec.schema.description === "string" ? spec.schema.description : "" });
      if (spec.sensitive || spec.cut) continue; // a secret is one field; past the bound, JSON
      if (spec.base === "group") walk(offeredOf(spec), here.steps, here.titles, here.raw);
      else if (spec.base === "map") {
        const entry = entryOf(spec, "*");
        if (entry.base === "group") walk(offeredOf(entry), [...here.steps, { kind: "entry", name: "*" }], [...here.titles, "an entry"], `${here.raw}.*`);
      } else if (spec.base === "list") {
        const item = itemOf(spec, 0);
        if (item.base === "group") walk(offeredOf(item), [...here.steps, { kind: "item", name: "0" }], [...here.titles, "an item"], `${here.raw}[]`);
      }
    }
  };
  walk(offeredOf(body, kind), [], [], "");
  const byType = cache.get(body.type) ?? new Map<string, Setting[]>();
  byType.set(key, out);
  cache.set(body.type, byType);
  return out;
}

const normal = (text: string) => text.trim().toLowerCase().replace(/\s+/g, " ");
export const wordsOf = (query: string): string[] => normal(query).split(" ").filter((w) => w !== "");

/** The settings every word typed is in (titles, raw path or description), a match in a title or the raw path before
 * one only in the description, top-level before nested, then by title; at most 50 shown. Nothing typed: the
 * top-level settings, by title. */
export function findSettings(all: Setting[], query: string): { shown: Setting[]; total: number } {
  const words = wordsOf(query);
  const byTitle = (a: Setting, b: Setting) => a.titles.join(" ").localeCompare(b.titles.join(" "));
  if (words.length === 0) {
    const top = all.filter((s) => s.steps.length === 1).sort(byTitle);
    return { shown: top, total: top.length };
  }
  const hits = all
    .map((s) => {
      const named = normal(`${s.titles.join(" ")} ${s.raw}`);
      const told = normal(s.description);
      const found = words.every((w) => named.includes(w) || told.includes(w));
      return found ? { s, rank: words.every((w) => named.includes(w)) ? 0 : 1 } : null;
    })
    .filter((x): x is { s: Setting; rank: number } => x !== null)
    .sort((a, b) => a.rank - b.rank || a.s.steps.length - b.s.steps.length || byTitle(a.s, b.s))
    .map((x) => x.s);
  return { shown: hits.slice(0, MAX_SHOWN), total: hits.length };
}

/** What the list says under it: how many are shown, or that none matches. */
export function findWords(query: string, shown: number, total: number): string {
  if (wordsOf(query).length === 0) return `${total} settings; the list scrolls.`;
  if (total === 0) return `No setting matches "${query.trim()}", by name or description.`;
  return total > shown ? `${shown} of ${total} shown: type more to narrow.` : total === 1 ? "1 setting matches." : `${total} settings match.`;
}
