// SPDX-License-Identifier: Apache-2.0
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger";
const styles: Record<Variant, string> = {
  primary: "bg-accent text-on-accent border-accent hover:opacity-90",
  secondary: "bg-surface text-ink border-line-strong hover:bg-surface-2",
  danger: "bg-surface text-danger border-danger hover:bg-surface-2",
};

export function Button({ variant = "secondary", className = "", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...rest}
      className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-50 ${styles[variant]} ${className}`}
    />
  );
}
