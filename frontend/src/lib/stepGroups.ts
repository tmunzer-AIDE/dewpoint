// SPDX-License-Identifier: Apache-2.0
// The groups a plugin puts its steps in (4f-2, the Mist step design §4.1, §5.1): `x-group` at a config's root, a
// display annotation outside the contract hash. The add-step picker shows a plugin's groups instead of its steps (Mist's
// 85 resources, not its 294 steps); the drawer names a step's group under its title.
import type { NodeType } from "./workflows";

export type GroupKey = { plugin: string; title: string };
/** A plugin's group and its steps, by title. */
export type StepGroup = GroupKey & { types: NodeType[] };
/** The steps offered: each plugin's groups, by title, and the steps no group holds, in the order given. */
export type Grouped = { plugins: { plugin: string; groups: StepGroup[] }[]; loose: NodeType[] };

const WORDS_SHOWN = 6;

const byTitle = (a: { title: string }, b: { title: string }) => a.title.localeCompare(b.title);
const normal = (text: string) => text.trim().toLowerCase().replace(/\s+/g, " ");

/** A step's group, when its config's root names one with words. */
export function groupOf(type: NodeType): GroupKey | null {
  const group = (type.config_schema as Record<string, unknown>)["x-group"];
  if (typeof group !== "object" || group === null) return null;
  const { plugin, title } = group as Record<string, unknown>;
  return typeof plugin === "string" && plugin.trim() !== "" && typeof title === "string" && title.trim() !== ""
    ? { plugin, title }
    : null;
}

export function grouped(types: NodeType[]): Grouped {
  const plugins = new Map<string, Map<string, NodeType[]>>();
  const loose: NodeType[] = [];
  for (const type of types) {
    const group = groupOf(type);
    if (group === null) {
      loose.push(type);
      continue;
    }
    const groups = plugins.get(group.plugin) ?? new Map<string, NodeType[]>();
    plugins.set(group.plugin, groups);
    groups.set(group.title, [...(groups.get(group.title) ?? []), type]);
  }
  return {
    plugins: [...plugins]
      .map(([plugin, groups]) => ({
        plugin,
        groups: [...groups].map(([title, members]) => ({ plugin, title, types: [...members].sort(byTitle) })).sort(byTitle),
      }))
      .sort((a, b) => a.plugin.localeCompare(b.plugin)),
    loose,
  };
}

/** What a group's steps do, by their titles' first words, each once: "Create, Delete, Get, List, Update". */
export function actionWords(group: StepGroup): string {
  const words = [...new Set(group.types.map((t) => t.title.split(" ")[0]!).filter((w) => w !== ""))];
  return words.length > WORDS_SHOWN ? `${words.slice(0, WORDS_SHOWN).join(", ")}…` : words.join(", ");
}

/** A group is found by each word typed, in its title or in one of its steps' refs ("wlan", "site_settings"). */
export function groupMatches(group: StepGroup, query: string): boolean {
  const words = normal(query).split(" ").filter((w) => w !== "");
  const title = group.title.toLowerCase();
  return words.length > 0 && words.every((w) => title.includes(w) || group.types.some((t) => t.ref.toLowerCase().includes(w)));
}

/** A grouped step is found by itself when its title starts with what's typed, or when a ref is typed (it has a dot) and
 * its ref holds it: "wlan" alone finds the groups, not every WLAN step. */
export function stepMatches(type: NodeType, query: string): boolean {
  const q = normal(query);
  return q !== "" && (type.title.toLowerCase().startsWith(q) || (q.includes(".") && type.ref.toLowerCase().includes(q)));
}
