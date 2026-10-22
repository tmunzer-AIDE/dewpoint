// SPDX-License-Identifier: Apache-2.0
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

// A control's boundary is 3:1 against its surface (line-control, WCAG 1.4.11); red when its value is refused.
// Full width of its column, never wider: an input's own width (20 characters) would push a narrow screen sideways.
const CONTROL = "min-h-11 w-full min-w-0 rounded-lg border bg-surface px-3 text-body-lg text-ink placeholder:text-muted";

/** A control's classes: its boundary 3:1 against its surface (line-control), red when its value is refused. */
export const controlClass = (invalid: boolean): string => `${CONTROL} ${invalid ? "border-danger" : "border-line-control"}`;

interface Labelled {
  label: ReactNode; // its text, with what a form adds beside it (a "required" tag)
  hint?: ReactNode;
  error?: string;
}

/** A field's own: what a start form's picker adds (the 4f-3 design §5.2). */
interface Around {
  /** What follows the hint and the error: the picker's choices. */
  below?: ReactNode;
  /** More ids describing the control, after its hint and error: a picker's status line. */
  describedBy?: string;
}

/** The label, the control (given its id and description ids), then its hint and error, each described by the control.
 * Its id is the caller's when given: what's below the control may point at it. */
function Frame({ id: given, label, hint, error, below, describedBy: more, control }: Labelled & Around & {
  id?: string; control: (props: { id: string; describedBy?: string; className: string }) => ReactNode;
}) {  // prettier-ignore
  const own = useId();
  const id = given ?? own;
  const described = [hint ? `${id}-hint` : null, error ? `${id}-err` : null, more ?? null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-small font-semibold">{label}</label>
      {control({ id, describedBy: described, className: controlClass(!!error) })}
      {hint && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
      {error && <p id={`${id}-err`} className="text-small text-danger">{error}</p>}
      {below}
    </div>
  );
}

export function Field({ id, label, hint, error, below, describedBy: more, ...input }: InputHTMLAttributes<HTMLInputElement> & Labelled & Around) {
  return (
    <Frame id={id} label={label} hint={hint} error={error} below={below} describedBy={more} control={({ id, describedBy, className }) => (
      <input id={id} {...input} aria-invalid={!!error} aria-describedby={describedBy} className={className} />
    )} />
  );
}

export function Select({ label, hint, error, children, ...select }: SelectHTMLAttributes<HTMLSelectElement> & Labelled) {
  return (
    <Frame label={label} hint={hint} error={error} control={({ id, describedBy, className }) => (
      <select id={id} {...select} aria-invalid={!!error} aria-describedby={describedBy} className={className}>
        {children}
      </select>
    )} />
  );
}

/** Text of several lines, like JSON: a fixed-width face, its height from `rows`. */
export function TextArea({ label, hint, error, ...area }: TextareaHTMLAttributes<HTMLTextAreaElement> & Labelled) {
  return (
    <Frame label={label} hint={hint} error={error} control={({ id, describedBy, className }) => (
      <textarea id={id} {...area} aria-invalid={!!error} aria-describedby={describedBy} className={`${className} py-2 font-mono text-small`} />
    )} />
  );
}
