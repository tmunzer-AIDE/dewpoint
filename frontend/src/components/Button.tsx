// SPDX-License-Identifier: Apache-2.0
import type { ComponentProps } from "react";
import type { ButtonVariant } from "../styles/tokenNames";

// Each variant's states, as literal classes Tailwind can see. Button.test.tsx holds them to BUTTON_STATES, the data
// tokens.test.ts holds to the contrast floors. Hover and press apply only while enabled.
const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "text-on-accent bg-accent border-accent enabled:hover:text-on-accent enabled:hover:bg-accent-hover " +
    "enabled:hover:border-accent-hover enabled:active:text-on-accent enabled:active:bg-accent-pressed " +
    "enabled:active:border-accent-pressed",
  secondary:
    "text-ink bg-surface border-line-strong enabled:hover:text-ink enabled:hover:bg-surface-hover " +
    "enabled:hover:border-line-strong enabled:active:text-ink enabled:active:bg-surface-pressed " +
    "enabled:active:border-line-strong",
  simulate:
    "text-sim bg-surface border-sim enabled:hover:text-sim enabled:hover:bg-sim-bg enabled:hover:border-sim " +
    "enabled:active:text-sim enabled:active:bg-surface-pressed enabled:active:border-sim",
  "live-outline":
    "text-live bg-surface border-live enabled:hover:text-live enabled:hover:bg-live-bg enabled:hover:border-live " +
    "enabled:active:text-live-hover enabled:active:bg-surface-pressed enabled:active:border-live",
  live:
    "text-on-live bg-live border-live enabled:hover:text-on-live enabled:hover:bg-live-hover " +
    "enabled:hover:border-live-hover enabled:active:text-on-live enabled:active:bg-live-pressed " +
    "enabled:active:border-live-pressed",
  "danger-outline":
    "text-danger bg-surface border-danger enabled:hover:text-danger enabled:hover:bg-danger-bg " +
    "enabled:hover:border-danger enabled:active:text-danger enabled:active:bg-surface-pressed " +
    "enabled:active:border-danger",
  danger:
    "text-on-danger bg-danger border-danger enabled:hover:text-on-danger enabled:hover:bg-danger-hover " +
    "enabled:hover:border-danger-hover enabled:active:text-on-danger enabled:active:bg-danger-pressed " +
    "enabled:active:border-danger-pressed",
};

const SIZES = {
  sm: "min-h-8 px-3 text-small", // table rows ("Verify")
  md: "min-h-9 px-3 text-body", // headers and toolbars
  lg: "min-h-11 px-4 text-body", // forms and page actions
} as const;

const DISABLED = "disabled:bg-disabled-bg disabled:border-disabled-line disabled:text-disabled-ink";

export function Button({
  variant = "secondary",
  size = "lg",
  type = "button",
  className = "",
  ...rest
}: ComponentProps<"button"> & { variant?: ButtonVariant; size?: keyof typeof SIZES }) {
  return (
    <button
      {...rest}
      type={type}
      className={`inline-flex items-center justify-center gap-2 rounded-lg border font-medium ${SIZES[size]} ${VARIANTS[variant]} ${DISABLED} ${className}`}
    />
  );
}
