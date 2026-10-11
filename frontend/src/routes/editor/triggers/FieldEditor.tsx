// SPDX-License-Identifier: Apache-2.0
// A field of the input, edited in its row (4c-3b; the InputFields board): its name, label, type, description, whether
// it's required or sensitive, its default and a Choice's values. Each control writes as it changes, a control's edits
// one undo step (ruling 8). A name is held while it's typed and applied when focus leaves it or Enter is pressed; a
// default that doesn't parse is held (ruling 113), and one typed over a default that has since changed is written only
// by Apply here. A sensitive field has no default and no Choice: either would be written into the workflow, which the
// server refuses (§3.8).
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
import { Field, Select, controlClass } from "../../../components/Field";
import { FIELD_TYPES, fieldPointer, inputOf, removeField, setField, setSettings, type FieldType, type InputField } from "../../../lib/input";
import { parseNumber } from "../../../lib/unapplied";
import { FieldFrame } from "../drawer/FieldFrame";
import { useText } from "../drawer/scalars";
import { useTriggers } from "./context";
import { Check, Problems, StaleEdit, Values, heldWhy, problemsAt, writeTyped } from "./parts";

const SENSITIVE = "Kept apart from run history. A sensitive field has no default: it would be written into the workflow.";
const NO_CHOICE = "A sensitive field can't be a Choice: its values would be written into the workflow.";

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

export function FieldEditor({ field, onClose, onRenamed }: { field: InputField; onClose: () => void; onRenamed: (to: string) => void }) {
  const t = useTriggers();
  const { actions } = t;
  const disabled = !t.editable;
  const pointer = fieldPointer(field.name);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.querySelector("input")?.focus(), []);
  const set = (patch: Partial<InputField>, key: string) =>
    actions.update((d) => setSettings(d, { input_schema: setField(inputOf(d), field.name, patch) }), null, `${pointer}/${key}`);
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
      <Field label="Label" value={field.label} disabled={disabled} onChange={(e) => set({ label: e.target.value }, "title")} />
      <Select
        label="Type" value={field.type} disabled={disabled} hint={field.sensitive ? NO_CHOICE : undefined}
        onChange={(e) => set({ type: e.target.value as FieldType }, "type")}
      >
        {FIELD_TYPES.map((x) => <option key={x.value} value={x.value} disabled={x.value === "choice" && field.sensitive}>{x.label}</option>)}
      </Select>
      <Field label="Description (optional)" value={field.description} disabled={disabled} onChange={(e) => set({ description: e.target.value }, "description")} />
      <Check label="Required" checked={field.required} disabled={disabled} onChange={(required) => set({ required }, "required")} />
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
      <Default field={field} pointer={pointer} disabled={disabled} set={set} />
      <Problems problems={problemsAt(t.check, pointer)} />
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
