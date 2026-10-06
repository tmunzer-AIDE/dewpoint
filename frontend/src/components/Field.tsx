// SPDX-License-Identifier: Apache-2.0
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

// A control's boundary is 3:1 against its surface (line-control, WCAG 1.4.11); red when its value is refused.
// Full width of its column, never wider: an input's own width (20 characters) would push a narrow screen sideways.
const CONTROL = "min-h-11 w-full min-w-0 rounded-lg border bg-surface px-3 text-body-lg text-ink placeholder:text-muted";

interface Labelled {
  label: string;
  hint?: ReactNode;
  error?: string;
}

/** The label, the control (given its id and description ids), then its hint and error, each described by the control. */
function Frame({ label, hint, error, control }: Labelled & {
  control: (props: { id: string; describedBy?: string; className: string }) => ReactNode;
}) {
  const id = useId();
  const described = [hint ? `${id}-hint` : null, error ? `${id}-err` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-small font-semibold">{label}</label>
      {control({ id, describedBy: described, className: `${CONTROL} ${error ? "border-danger" : "border-line-control"}` })}
      {hint && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
      {error && <p id={`${id}-err`} className="text-small text-danger">{error}</p>}
    </div>
  );
}

export function Field({ label, hint, error, ...input }: InputHTMLAttributes<HTMLInputElement> & Labelled) {
  return (
    <Frame label={label} hint={hint} error={error} control={({ id, describedBy, className }) => (
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
