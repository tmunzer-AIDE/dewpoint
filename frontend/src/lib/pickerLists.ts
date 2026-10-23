// SPDX-License-Identifier: Apache-2.0
// The lists a start-form picker can name (the 4f-3 design §5.7): one per options field across the active node types, in
// the words its plugin gives it (`x-list`, 4f-3a: "Mist · Org sites", noun "sites"), each with the node the picker
// names: a read-only `.get` whose only required config is its connection and the field (one per Mist list), the first by
// ref; failing that, the first read-only one by ref. A field whose list has no words isn't offered.
import { isObject } from "./schemaForm";
import type { NodeType } from "./workflows";

export type PickerList = { field: string; label: string; plugin: string; noun: string; node: string; credentials: string[] };

/** A type's options field's list words, or null when it has none. */
function wordsOf(t: NodeType, field: string): { plugin: string; title: string; noun: string } | null {
  const props = isObject(t.config_schema.properties) ? t.config_schema.properties : {};
  const x = isObject(props[field]) ? props[field]["x-list"] : undefined;
  return isObject(x) && typeof x.plugin === "string" && typeof x.title === "string" && typeof x.noun === "string"
    ? { plugin: x.plugin, title: x.title, noun: x.noun }
    : null;  // prettier-ignore
}

/** Whether a type's required config is its connection and `field` alone. */
function takesOnly(t: NodeType, field: string): boolean {
  const props = isObject(t.config_schema.properties) ? t.config_schema.properties : {};
  const connection = Object.keys(props).find((k) => isObject(props[k]) && typeof props[k]["x-dewpoint-connection"] === "string");
  const required = Array.isArray(t.config_schema.required) ? (t.config_schema.required as unknown[]) : [];
  return connection !== undefined && required.length === 2 && required.includes(connection) && required.includes(field);
}

export function pickerLists(types: NodeType[]): PickerList[] {
  const byRef = types.filter((t) => t.state === "active" && t.side_effect === "none").sort((a, b) => (a.ref < b.ref ? -1 : 1));
  const fields = [...new Set(byRef.flatMap((t) => t.options))];
  return fields
    .flatMap((field): PickerList[] => {
      const offering = byRef.filter((t) => t.options.includes(field) && wordsOf(t, field) !== null);
      const node = offering.find((t) => t.type.endsWith(".get") && takesOnly(t, field)) ?? offering[0];
      const words = node ? wordsOf(node, field) : null;
      if (!node || !words) return [];
      return [{ field, label: `${words.plugin} · ${words.title}`, plugin: words.plugin, noun: words.noun, node: node.ref, credentials: node.credentials }];
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}

export const listOf = (lists: PickerList[], field: string): PickerList | undefined => lists.find((l) => l.field === field);
