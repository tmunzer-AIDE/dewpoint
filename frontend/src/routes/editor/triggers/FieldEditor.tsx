// SPDX-License-Identifier: Apache-2.0
// A field of the input, edited in its row (4c-3b; the InputFields board): its name, label, type, description, whether
// it's required or sensitive, its default and a Choice's values. Each control writes as it changes, a control's edits
// one undo step (ruling 8). A name is held while it's typed and applied when focus leaves it or Enter is pressed; a
// default that doesn't parse is held (ruling 113), and one typed over a default that has since changed is written only
// by Apply here. A sensitive field has no default and no Choice: either would be written into the workflow, which the
// server refuses (§3.8). A Choice from a connection (the 4f-3 design §5.7) has its list and its connection instead of a
// default, values or sensitivity; until both are chosen the editor holds the half choice and the field stays plain
// text: closing the editor drops it, and so does any change to the field not made here (an undo).
import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Field, Select, controlClass } from "../../../components/Field";
import { FIELD_TYPES, fieldPointer, inputOf, inputRows, removeField, setField, setSettings, type FieldType, type InputField } from "../../../lib/input";
import { parseNumber } from "../../../lib/unapplied";
import { FieldFrame } from "../drawer/FieldFrame";
import { useText } from "../drawer/scalars";
import { useTriggers } from "./context";
import { Check, Problems, StaleEdit, Values, heldWhy, problemsAt, writeTyped } from "./parts";
import { PickerChoice } from "./PickerChoice";

const SENSITIVE = "Kept apart from run history. A sensitive field has no default: it would be written into the workflow.";
const NO_CHOICE = "A sensitive field can't be a Choice, nor a Choice from a connection: its values would be written into the workflow, the names picked shown.";

/** A field as it reads, whatever its name: what tells a change made elsewhere (an undo) from one made here. */
const sigOf = (f: InputField) => JSON.stringify({ ...f, name: "" });

/** A whole number's or a number's default: held while it doesn't parse, written once it does. */
function NumberDefault({ field, pointer, disabled }: { field: InputField; pointer: string; disabled: boolean }) {
  const { actions } = useTriggers();
  const at = `${pointer}/default`;
  const whole = field.type === "whole";
  const held = actions.held("number", at);
  const show = (v: unknown) => (typeof v === "number" ? String(v) : "");
  const [text, setText] = useText(
    field.default,
    show,
    (t, v) => {
      const parsed = parseNumber(t, whole);
      return "value" in parsed && parsed.value === v;
    },
    held?.text,
  );
  return (
    <div className="flex flex-col gap-1.5">
      <FieldFrame label="Default" required={false} hint={null} local={heldWhy(actions, "number", at)} problems={[]}>
        {({ id, describedBy, invalid }) => (
          <input
            id={id} type="text" inputMode="decimal" value={held?.text ?? text} disabled={disabled} spellCheck={false}
            aria-describedby={describedBy} aria-invalid={invalid}
            onChange={(e) => {
              const t = e.target.value;
              setText(t);
              const parsed = parseNumber(t, whole);
              const holding = { path: ["input_schema", "properties", field.name, "default"], label: `${field.name}'s default`, text: t, whole };
              writeTyped(actions, "number", at, holding, "problem" in parsed ? parsed.problem : null, () =>
                "problem" in parsed ? null : actions.update((d) => setSettings(d, { input_schema: setField(inputOf(d), field.name, { default: parsed.value }) }), null, at),
              );
            }}
            className={controlClass(invalid)}
          />
        )}
      </FieldFrame>
      <StaleEdit kind="number" at={at} onDiscard={() => setText(show(field.default))} />
    </div>
  );  // prettier-ignore
}

function Default({ field, pointer, disabled, set }: {
  field: InputField; pointer: string; disabled: boolean; set: (patch: Partial<InputField>, key: string) => void;
}) {  // prettier-ignore
  if (field.sensitive) return <Field label="Default" value="" disabled />;
  if (field.type === "whole" || field.type === "number") return <NumberDefault field={field} pointer={pointer} disabled={disabled} />;
  if (field.type === "yesno" || field.type === "choice") {
    const options = field.type === "yesno" ? [["true", "Yes"], ["false", "No"]] : field.values.map((v) => [JSON.stringify(v), v]);
    return (
      <Select
        label="Default" value={"default" in field ? JSON.stringify(field.default) : ""} disabled={disabled}
        onChange={(e) => set({ default: e.target.value === "" ? undefined : (JSON.parse(e.target.value) as unknown) }, "default")}
      >
        <option value="">None</option>
        {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </Select>
    );  // prettier-ignore
  }
  return (
    <Field
      label="Default" value={typeof field.default === "string" ? field.default : ""} disabled={disabled}
      placeholder={field.type === "datetime" ? "2026-10-11T08:00:00Z" : undefined}
      onChange={(e) => set({ default: e.target.value === "" ? undefined : e.target.value }, "default")}
    />
  );  // prettier-ignore
}

export function FieldEditor({ field, focusDefault = false, onClose, onRenamed }: {
  field: InputField; focusDefault?: boolean; onClose: () => void; onRenamed: (to: string) => void;
}) {  // prettier-ignore
  const t = useTriggers();
  const { actions } = t;
  const disabled = !t.editable;
  const pointer = fieldPointer(field.name);
  const box = useRef<HTMLDivElement>(null);
  // Its first control takes focus, or its Default when "Go to it" was for the default (4c-3b's final review).
  useEffect(() => box.current?.querySelector<HTMLElement>(focusDefault ? "[data-default] input, [data-default] select" : "input")?.focus(), []);
  const set = (patch: Partial<InputField>, key: string) =>
    actions.update((d) => setSettings(d, { input_schema: setField(inputOf(d), field.name, patch) }), null, `${pointer}/${key}`);
  // A Choice from a connection chosen without its list and connection, held here against the field as it then read.
  const [half, setHalf] = useState<{ list: string | null; base: string } | null>(null);
  const sig = sigOf(field);
  const held = half !== null && half.base === sig ? half : null;
  /** The field as `patch` would leave it, as `sigOf` reads it. */
  const after = (patch: Partial<InputField>) => {
    const row = inputRows(setField(inputOf(t.doc), field.name, patch)).find((r) => r.kind === "field" && r.field.name === field.name);
    return row?.kind === "field" ? sigOf(row.field) : sig;
  };
  /** A write made here, which a half choice outlives. */
  const write = (patch: Partial<InputField>, key: string) => {
    const base = held ? after(patch) : null;
    const why = set(patch, key);
    if (why === null && base !== null) setHalf((h) => h && { ...h, base });
    return why;
  };
  const picking = held !== null || field.type === "picker";
  const pickerAt = `${pointer}/x-dewpoint-picker`;
  /** The picker written once its list and its connection are both chosen (one undo step); short of that, plain text and
   * the list held. */
  const choose = (list: { field: string; node: string } | null, connection: string | null) => {
    if (list !== null && connection !== null) {
      if (set({ type: "picker", picker: { node: list.node, field: list.field, connection } }, "x-dewpoint-picker") === null) setHalf(null);
    } else if (field.type === "picker") {
      const base = after({ type: "text" });
      if (set({ type: "text" }, "x-dewpoint-picker") === null) setHalf({ list: list?.field ?? null, base });
    } else setHalf({ list: list?.field ?? null, base: sig });
  };
  const toType = (to: FieldType) => {
    if (to !== "picker") {
      setHalf(null);
      set({ type: to }, "type");
    } else if (field.type !== "picker") {
      // Held as plain text until its list and connection are chosen: whatever else the type was goes now.
      const plain = field.type !== "text" || "default" in field;
      const base = plain ? after({ type: "text", default: undefined }) : sig;
      if (!plain || set({ type: "text", default: undefined }, "type") === null) setHalf({ list: null, base });
    }
  };
  const name = actions.held("name", pointer);
  /** The name typed, applied: whether the field may close (a refused one stays, with why). */
  const applyName = (): boolean => {
    if (!name) return true;
    const to = name.text.trim();
    if (to === field.name) {
      actions.release("name", pointer);
      return true;
    }
    if (actions.apply("name", pointer) !== null) return false;
    onRenamed(to);
    return true;
  };
  return (
    <div
      ref={box}
      role="group"
      aria-label={`The field ${field.name}`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // closes the field, not the panel
          if (applyName()) onClose();
        }
      }}
      className="flex flex-col gap-3 rounded-lg border border-line-strong p-3"
    >
      <Field
        label="Name" value={name?.text ?? field.name} disabled={disabled} spellCheck={false} autoCapitalize="off"
        hint={`Steps read it as trigger.${field.name}. Lowercase letters, digits and _.`} error={heldWhy(actions, "name", pointer) ?? undefined}
        onChange={(e) => {
          const text = e.target.value;
          if (text === field.name) actions.release("name", pointer);
          else actions.hold("name", pointer, { path: ["input_schema", "properties"], label: `${field.name}'s name`, text, why: null, from: field.name });
        }}
        onBlur={() => void applyName()}
        onKeyDown={(e) => {
          if (e.key === "Enter") applyName();
        }}
      />
      <StaleEdit
        kind="name" at={pointer}
        onApply={() => {
          actions.rebase("name", pointer);
          applyName();
        }}
      />
      <Field label="Label" value={field.label} disabled={disabled} onChange={(e) => write({ label: e.target.value }, "title")} />
      <Select
        label="Type" value={held ? "picker" : field.type} disabled={disabled} hint={field.sensitive ? NO_CHOICE : undefined}
        onChange={(e) => toType(e.target.value as FieldType)}
      >
        {FIELD_TYPES.map((x) => (
          <option key={x.value} value={x.value} disabled={(x.value === "choice" || x.value === "picker") && field.sensitive}>{x.label}</option>
        ))}
      </Select>
      {picking && (
        <PickerChoice
          picker={field.type === "picker" ? (field.picker ?? null) : null} held={held?.list ?? null} disabled={disabled}
          problems={problemsAt(t.check, pickerAt)} onChoose={choose}
        />
      )}
      <Field label="Description (optional)" value={field.description} disabled={disabled} onChange={(e) => write({ description: e.target.value }, "description")} />
      <Check label="Required" checked={field.required} disabled={disabled} onChange={(required) => write({ required }, "required")} />
      {!picking && (
        <>
          <Check
            label="Sensitive" checked={field.sensitive} disabled={disabled || field.type === "choice"} hint={field.type === "choice" ? NO_CHOICE : SENSITIVE}
            onChange={(sensitive) => set({ sensitive }, "x-sensitive")}
          />
          {field.type === "choice" && (
            <Values
              label={`The field ${field.name}'s values`} values={field.values} disabled={disabled}
              hint="A run's value must be one of these, as written. Up to 200."
              onChange={(values) => set({ values }, "enum")}
            />
          )}
          <div data-default className="flex flex-col">
            <Default field={field} pointer={pointer} disabled={disabled} set={set} />
          </div>
        </>
      )}
      <Problems problems={problemsAt(t.check, pointer).filter((d) => !picking || (d.field !== pickerAt && !d.field!.startsWith(`${pickerAt}/`)))} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" onClick={() => applyName() && onClose()}>Done</Button>
        {!disabled && (
          <Button
            size="sm" variant="danger-outline"
            onClick={() => {
              actions.discard(pointer);
              if (actions.update((d) => setSettings(d, { input_schema: removeField(inputOf(d), field.name) }), `Removed the field ${field.name}.`) === null) onClose();
            }}
          >
            Remove field
          </Button>
        )}
      </div>
    </div>
  );  // prettier-ignore
}
