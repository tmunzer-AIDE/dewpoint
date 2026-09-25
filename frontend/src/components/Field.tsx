// SPDX-License-Identifier: Apache-2.0
import { useId, type InputHTMLAttributes, type ReactNode } from "react";

export function Field({ label, hint, error, ...input }:
  InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; error?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold">{label}</label>
      <input id={id} {...input} aria-invalid={!!error} aria-describedby={error ? `${id}-err` : undefined}
        className="min-h-11 rounded-lg border border-line-strong bg-surface px-3 text-[15px]" />
      {hint && <p className="text-[13px] text-muted">{hint}</p>}
      {error && <p id={`${id}-err`} className="text-[13px] text-danger">{error}</p>}
    </div>
  );
}
