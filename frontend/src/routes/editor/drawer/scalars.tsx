// SPDX-License-Identifier: Apache-2.0
// The controls for a fixed value (4c-1, ruling 5): text, a number, a yes or no, one of a list, and JSON as the engine
// reads it (ruling 15). Each writes through its field. What it can't write yet (a number that doesn't parse, JSON
// still being typed) the editor holds (ruling 18): nothing unsaved looks saved (D19), and nothing typed is lost to a
// tab or a toggle.
import { useState } from "react";
import { controlClass } from "../../../components/Field";
import type { FieldSpec } from "../../../lib/schemaForm";
import { parseNumber } from "../../../lib/unapplied";
import { useDrawer } from "./context";
import type { Described } from "./FieldFrame";

export interface ControlProps extends Described {
  spec: FieldSpec;
  value: unknown; // a `literal` envelope's payload, or the value as written
  literal: boolean; // the value is a literal's payload: written back as one (ruling 15)
  disabled: boolean;
  /** Writes a new value (undefined: emptied); `typed` makes it part of the field's typing (ruling 8). Why it wasn't
   * written, or null. */
  onChange: (value: unknown, typed: boolean) => string | null;
}

export const JSON_NOTE = 'As the engine reads it: an object with a "$value" key is computed.';
export const LITERAL_NOTE = 'Written as a literal: kept as data, "$value" included.';
export const CUT_NOTE = "Shown as JSON: its schema repeats itself, or nests too deep for a form.";

/** A control's own text, kept while it still means the value it shows ("2." while 2.5 is typed), and replaced when
 * the value changes elsewhere (an undo, a replace). It starts from what the editor holds for it, if anything. */
export function useText(value: unknown, show: (v: unknown) => string, means: (text: string, v: unknown) => boolean, held?: string) {
  const [text, setText] = useState(() => held ?? show(value));
  const [seen, setSeen] = useState(value);
  if (!Object.is(seen, value)) {
    setSeen(value);
    if (!means(text, value)) setText(show(value));
  }
  return [text, setText] as const;
}

const asText = (v: unknown): string => (typeof v === "string" ? v : v === undefined || v === null ? "" : JSON.stringify(v));

export function TextControl({ spec, value, literal, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const drawer = useDrawer();
  const held = drawer.held("text", spec.pointer);
  return (
    <input
      id={id} type="text" value={held?.text ?? asText(value)} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
      onChange={(e) => {
        const text = e.target.value;
        const why = onChange(text === "" ? undefined : text, true);
        // Released only once it's written; refused, it stays the person's, with why (ruling 18).
        if (why === null) drawer.release("text", spec.pointer);
        // The edit keeps the reading it began with, a literal's or not, whatever an undo does under it.
        else drawer.hold("text", spec.pointer, { path: spec.path, label: spec.label, text, why, literal: held?.literal ?? literal, entry: spec.entry });
      }}
      className={controlClass(invalid)}
    />
  );  // prettier-ignore
}

export function NumberControl({ spec, value, literal, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const drawer = useDrawer();
  const whole = spec.base === "integer";
  const held = drawer.held("number", spec.pointer);
  // Its own text keeps "2." while 2.5 is typed; what the editor holds shows over it, whatever the value under it does
  // (an undo, a remount: the review of revision 2).
  const [text, setText] = useText(
    value,
    asText,
    (t, v) => {
      const parsed = parseNumber(t, whole);
      return "value" in parsed && (parsed.value === undefined ? v === undefined || v === null : parsed.value === v);
    },
    held?.text,
  );
  return (
    <input
      id={id} type="text" value={held?.text ?? text} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
      onChange={(e) => {
        const typed = e.target.value;
        setText(typed);
        const parsed = parseNumber(typed, whole);
        const why = "problem" in parsed ? parsed.problem : onChange(parsed.value, true);
        // Released only once it's written; refused, it stays the person's, with why (ruling 18).
        if (why === null) drawer.release("number", spec.pointer);
        else drawer.hold("number", spec.pointer, { path: spec.path, label: spec.label, text: typed, why, whole, literal: held?.literal ?? literal, entry: spec.entry });
      }}
      className={controlClass(invalid)}
    />
  );  // prettier-ignore
}

export function BooleanControl({ value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  return (
    // 20 px, alone on its row: its 24 px target spacing holds (WCAG 2.5.8).
    <input
      id={id} type="checkbox" checked={value === true} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => onChange(e.target.checked, false)}
      className="size-[20px] self-start accent-accent"
    />
  );  // prettier-ignore
}

export function EnumControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const choices = (spec.schema.enum as unknown[]).filter((v): v is string => typeof v === "string");
  const current = typeof value === "string" ? value : "";
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, false)}
      className={controlClass(invalid)}
    >
      <option value="">{spec.required ? "Choose…" : "Not set"}</option>
      {current !== "" && !choices.includes(current) && <option value={current}>{current} (not one of its choices)</option>}
      {choices.map((c) => (
        <option key={c} value={c}>{c}</option>
      ))}
    </select>
  );  // prettier-ignore
}

/** JSON as the engine reads it (ruling 15). What's typed is the editor's until focus leaves its field, then applied
 * (ruling 18; the field does it, so its own Discard never applies it first): a half-typed edit never saves, one that
 * takes ports away asks once (ruling 9), and a tab or a toggle keeps it. */
export function JsonControl({ spec, value, literal, id, describedBy, invalid, disabled }: ControlProps) {
  const drawer = useDrawer();
  const held = drawer.held("json", spec.pointer);
  const shown = value === undefined ? "" : JSON.stringify(value, null, 2);
  const text = held?.text ?? shown;
  return (
    <textarea
      id={id} value={text} disabled={disabled} spellCheck={false} autoCapitalize="off"
      rows={Math.min(12, Math.max(3, text.split("\n").length))}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => {
        if (e.target.value === shown) drawer.release("json", spec.pointer);
        // The edit keeps the reading it began with: text typed as a literal's data stays data, whatever an undo does
        // under it (the review of revision 3).
        else drawer.hold("json", spec.pointer, { path: spec.path, label: spec.label, text: e.target.value, why: null, literal: held?.literal ?? literal, entry: spec.entry });
      }}
      className={`${controlClass(invalid)} py-2 font-mono text-small`}
    />
  );  // prettier-ignore
}
