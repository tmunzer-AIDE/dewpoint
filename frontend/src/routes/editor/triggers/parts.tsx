// SPDX-License-Identifier: Apache-2.0
// The Triggers panel's shared parts (4c-3b): a section with its heading and what it is ("Live · on version 3"), the
// current check's problems at a place in the settings, a Choice's values, text typed and held as a step's is, and focus
// given back once what held it is gone.
import { useId, useRef, type ReactNode, type Ref } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { STALE, type Holding, type UnappliedKind } from "../../../lib/unapplied";
import type { Diagnostic, Validation } from "../../../lib/workflows";
import { useTriggers, type PanelActions } from "./context";

/** A section of the panel; its heading takes focus when given a ref (where focus lands once what held it is gone), and
 * `box` is the section itself (where `useFocusBack` looks). */
export function Section({ id, title, note, heading, box, children }: {
  id: string; title: string; note: string; heading?: Ref<HTMLHeadingElement>; box?: Ref<HTMLElement>; children: ReactNode;
}) {  // prettier-ignore
  return (
    <section ref={box} aria-labelledby={id} className="flex flex-col gap-3 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <div className="flex flex-col">
        <h3 id={id} ref={heading} tabIndex={heading ? -1 : undefined} className="text-body font-semibold outline-none">{title}</h3>
        <span className="text-small text-muted">{note}</span>
      </div>
      {children}
    </section>
  );
}

/** The current check's problems at `pointer` and below; `exact` for those at it alone. */
export function problemsAt(check: Validation | null, pointer: string, exact = false): Diagnostic[] {
  return (check?.diagnostics ?? []).filter((d) => d.field !== null && (d.field === pointer || (!exact && d.field.startsWith(`${pointer}/`))));
}

/** Problems shown under what they're about, in the server's words (D18). */
export function Problems({ problems }: { problems: Diagnostic[] }) {
  if (problems.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1">
      {problems.map((d, i) => (
        <li key={`${d.code}:${d.field}:${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>
          {d.message}
          {d.fix && <span className="block text-muted">{d.fix}</span>}
        </li>
      ))}
    </ul>
  );
}

/** A checkbox with its label, and a hint the box is described by; `tall`: its row 44 px below 640 px (a field's editor,
 * the 4f-3 design §5.10). */
export function Check({ label, checked, disabled, hint, tall = false, onChange }: {
  label: string; checked: boolean; disabled: boolean; hint?: string; tall?: boolean; onChange: (checked: boolean) => void;
}) {  // prettier-ignore
  const id = useId();
  return (
    <div className="flex flex-col gap-0.5">
      <label htmlFor={id} className={`flex min-h-6 items-center gap-2 text-small${tall ? " max-sm:min-h-[44px]" : ""}`}>
        <input
          id={id} type="checkbox" checked={checked} disabled={disabled} aria-describedby={hint ? `${id}-hint` : undefined}
          onChange={(e) => onChange(e.target.checked)} className="size-[16px] accent-accent"
        />
        {label}
      </label>
      {hint && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
    </div>
  );  // prettier-ignore
}

/** A Choice's values, each its own text, removed by its ×; written as each changes. `tall`: 44 px below 640 px. */
export function Values({ label, values, disabled, hint, tall = false, onChange }: {
  label: string; values: string[]; disabled: boolean; hint: string; tall?: boolean; onChange: (values: string[]) => void;
}) {  // prettier-ignore
  return (
    <fieldset aria-label={label} className="flex min-w-0 flex-col gap-2">
      <legend className="text-small font-semibold">Values</legend>
      {values.map((v, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            aria-label={`Value ${i + 1}`} value={v} disabled={disabled} maxLength={200}
            onChange={(e) => onChange(values.map((x, j) => (j === i ? e.target.value : x)))}
            className={tall ? `${controlClass(false)} max-sm:min-h-[44px]` : controlClass(false)}
          />
          <Button
            size="sm" aria-label={`Remove ${v === "" ? `value ${i + 1}` : v}`} disabled={disabled} className={tall ? "max-sm:min-h-[44px]" : undefined}
            onClick={() => onChange(values.filter((_, j) => j !== i))}
          >
            ×
          </Button>
        </div>
      ))}
      <Button size="sm" className={tall ? "self-start max-sm:min-h-[44px]" : "self-start"} disabled={disabled || values.length >= 200} onClick={() => onChange([...values, ""])}>＋ Value</Button>
      <p className="text-small text-muted">{hint}</p>
    </fieldset>
  );  // prettier-ignore
}

/** Text typed in the panel, as a step's is (ruling 18): written when it can be (`write`, once it has no `problem`), held
 * with why when it can't. Typed over what has since changed (an undo, another edit), it's never written as it's typed,
 * only by Apply here: it stays held, with why (the review of revision 1). */
export function writeTyped(
  actions: PanelActions, kind: UnappliedKind, at: string, holding: Omit<Holding, "why">, problem: string | null, write: () => string | null,
): void {  // prettier-ignore
  const why = problem ?? (actions.stale(kind, at) ? STALE : write());
  if (why === null) actions.release(kind, at);
  else actions.hold(kind, at, { ...holding, why });
}

/** Why what's held at `at` isn't written, as its control says it: typed over what has since changed, or its own why. */
export function heldWhy(actions: PanelActions, kind: UnappliedKind, at: string): string | null {
  const held = actions.held(kind, at);
  return held === undefined ? null : actions.stale(kind, at) ? STALE : held.why;
}

/** A held edit typed over what has since changed: Apply here or Discard (ruling 18), then focus back on its control, the
 * first one beside it (WCAG 2.4.3). `onApply` applies it its own way; `onDiscard` puts the control's own text back. */
export function StaleEdit({ kind, at, onApply, onDiscard }: { kind: UnappliedKind; at: string; onApply?: () => void; onDiscard?: () => void }) {
  const { actions, editable } = useTriggers();
  const box = useRef<HTMLDivElement>(null);
  const held = actions.held(kind, at);
  if (!editable || held === undefined || !actions.stale(kind, at)) return null;
  const refocus = () => {
    const control = box.current?.parentElement?.querySelector<HTMLElement>("input, textarea");
    requestAnimationFrame(() => control?.focus());
  };
  return (
    <div ref={box} className="flex flex-wrap gap-2">
      <Button
        size="sm" aria-label={`Apply here: ${held.label}`}
        onClick={() => {
          if (onApply) onApply();
          else {
            actions.rebase(kind, at);
            actions.apply(kind, at);
          }
          refocus();
        }}
      >
        Apply here
      </Button>
      <Button
        size="sm" aria-label={`Discard the edit to ${held.label}`}
        onClick={() => {
          actions.release(kind, at);
          onDiscard?.();
          refocus();
        }}
      >
        Discard
      </Button>
    </div>
  );  // prettier-ignore
}

/** Gives focus back once what held it is gone (WCAG 2.4.3; the review of revision 1): after the next frame, to the first
 * element in `box` marked `data-back` with one of `keys`, tried in their order. */
export function useFocusBack<T extends HTMLElement>() {
  const box = useRef<T>(null);
  const back = (...keys: string[]) =>
    requestAnimationFrame(() => {
      const marked = [...(box.current?.querySelectorAll<HTMLElement>("[data-back]") ?? [])];
      for (const key of keys) {
        const to = marked.find((el) => el.dataset.back === key);
        if (to) return to.focus();
      }
    });
  return { box, back };
}
