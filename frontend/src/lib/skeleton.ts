// SPDX-License-Identifier: Apache-2.0
// A skeleton of an input (4d-1c; the simulation design §7.1, the InputJson board): every field its schema declares,
// optional ones too, filled with an empty value of its type, a list with one item so its shape shows. The Mist
// catalogue keeps no examples (plugins/mist/schemas.py), so a Mist event's input starts from this, labelled as such.
import { deref, isObject, type Schema } from "./schemaForm";

const DEPTH = 8; // deep enough for an event's shape; a schema that refers to itself stops here

const EMPTY: Record<string, unknown> = { string: "", integer: 0, number: 0, boolean: false, null: null };

export function skeletonOf(schema: unknown, root: Schema = isObject(schema) ? schema : {}, depth = 0): unknown {
  if (depth > DEPTH) return null;
  const s = deref(schema, root);
  for (const key of ["anyOf", "oneOf", "allOf"]) {
    const branches = s[key];
    if (Array.isArray(branches) && branches.length > 0 && s.type === undefined && s.properties === undefined) {
      return skeletonOf(branches[0], root, depth + 1);
    }
  }
  if (Array.isArray(s.enum) && s.enum.length > 0) return s.enum[0] as unknown;
  if ("const" in s) return s.const;
  const type = Array.isArray(s.type) ? ((s.type as unknown[]).find((t) => t !== "null") ?? "null") : s.type;
  if (type === "object" || isObject(s.properties)) {
    const properties = isObject(s.properties) ? s.properties : {};
    return Object.fromEntries(Object.entries(properties).map(([name, p]) => [name, skeletonOf(p, root, depth + 1)]));
  }
  if (type === "array") return s.items === undefined ? [] : [skeletonOf(s.items, root, depth + 1)];
  return typeof type === "string" && type in EMPTY ? EMPTY[type] : null;
}
