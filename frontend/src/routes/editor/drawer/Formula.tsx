// SPDX-License-Identifier: Apache-2.0
// A value computed when the step runs (4c-1, ruling 6; D19's formula mode): CEL in a monospace area, and how the
// server says it runs; the choice between a fixed value and a formula; a reference or text with references written
// elsewhere, shown as it is until it's replaced (pills come with 4c-2); and a sensitive field's fixed value, which is
// never shown (M25). A formula the graph's format refuses is held by the editor, with why (ruling 18).
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { MAX_FORMULA, formula, formulaOf, kindOf, referenceText } from "../../../lib/config";
import type { Expression } from "../../../lib/workflows";
import { useDrawer } from "./context";
import type { Described } from "./FieldFrame";
import { useText, type ControlProps } from "./scalars";

export type Mode = "fixed" | "formula";

export function FormulaControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const drawer = useDrawer();
  const held = drawer.held("formula", spec.pointer);
  const [text, setText] = useText(
    value,
    formulaOf,
    (t, v) => (t.trim() === "" ? kindOf(v) !== "cel" : formulaOf(v) === t),
    held?.text,
  );
  return (
    <textarea
      id={id} value={held?.text ?? text} rows={3} maxLength={MAX_FORMULA} spellCheck={false} autoCapitalize="off" disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => {
        setText(e.target.value);
        const why = onChange(e.target.value.trim() === "" ? undefined : formula(e.target.value), true);
        if (why === null) drawer.release("formula", spec.pointer);
        else drawer.hold("formula", spec.pointer, { path: spec.path, label: spec.label, text: e.target.value, why, entry: spec.entry });
      }}
      className={`${controlClass(invalid)} py-2 font-mono text-small`}
    />
  );  // prettier-ignore
}

/** How the server says a formula runs (engine-core §5.10), in 4b's words. */
export const runsText = (x: Expression | undefined): string | null =>
  !x ? null : x.mode === "local" ? "Runs inline" : `Runs as a separate step: ${x.reason ?? "no reason given"}`;

export function ModeSwitch({ label, mode, disabled, onChange }: {
  label: string; mode: Mode; disabled: boolean; onChange: (mode: Mode) => void;
}) {  // prettier-ignore
  return (
    // 1c's segmented look, never pills (outline §6): the chosen one pressed, by weight and fill.
    <div role="group" aria-label={`How ${label} is set`} className="inline-flex gap-px overflow-hidden rounded-lg border border-line-strong bg-line-strong">
      {(["fixed", "formula"] as const).map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={mode === m}
          disabled={disabled}
          onClick={() => {
            if (mode !== m) onChange(m);
          }}
          // Disabled, the chosen mode still reads by its weight (the owner's ruling O2).
          className={`min-h-8 px-3 text-small disabled:bg-disabled-bg disabled:text-muted ${mode === m ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          {m === "fixed" ? "Fixed" : "Formula"}
        </button>
      ))}
    </div>
  );
}

export function ReferenceView({ value, id, describedBy, fixed, toFormula, disabled, onFixed, onFormula }: Described & {
  value: unknown; fixed: boolean; toFormula: boolean; disabled: boolean; onFixed: () => void; onFormula: () => void;
}) {  // prettier-ignore
  return (
    <div className="flex flex-col gap-2">
      <output id={id} aria-describedby={describedBy} className="block break-all rounded-lg border border-line px-3 py-2 font-mono text-small">
        {referenceText(value)}
      </output>
      <p className="text-small text-muted">
        {kindOf(value) === "ref" ? "A reference to another value." : "Text with references."} Replace it to change it here.
      </p>
      {!disabled && (fixed || toFormula) && (
        <div className="flex flex-wrap gap-2">
          {fixed && <Button size="sm" onClick={onFixed}>Replace with a fixed value</Button>}
          {toFormula && <Button size="sm" onClick={onFormula}>Replace with a formula</Button>}
        </div>
      )}
    </div>
  );
}

export function SensitiveView({ id, describedBy, toFormula, disabled, onClear, onFormula }: Described & {
  toFormula: boolean; disabled: boolean; onClear: () => void; onFormula: () => void;
}) {  // prettier-ignore
  return (
    <div className="flex flex-col gap-2">
      <output id={id} aria-describedby={describedBy} className="block text-small">
        A fixed value is written here, which a sensitive field can&apos;t keep.
      </output>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onClear}>Clear it</Button>
          {toFormula && <Button size="sm" onClick={onFormula}>Replace with a formula</Button>}
        </div>
      )}
    </div>
  );
}
