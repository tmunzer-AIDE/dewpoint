// SPDX-License-Identifier: Apache-2.0
import * as SwitchPrimitive from "@radix-ui/react-switch";

/** An on/off control (Radix: role switch, Space toggles). A rounded rectangle, not a pill (outline §6): its track's
 * edge is 3:1 off the surface (line-control), its thumb 3:1 off the track in both states (PAIRS). */
export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className="inline-flex h-5 w-9 shrink-0 items-center rounded-md border border-line-control bg-surface-2 p-0.5 data-[state=checked]:border-accent data-[state=checked]:bg-accent disabled:cursor-not-allowed"
    >
      <SwitchPrimitive.Thumb className="block size-3.5 rounded-sm bg-line-control transition-transform duration-100 motion-reduce:transition-none data-[state=checked]:translate-x-4 data-[state=checked]:bg-on-accent" />
    </SwitchPrimitive.Root>
  );
}
