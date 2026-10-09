// SPDX-License-Identifier: Apache-2.0
import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

/** Tabs (Radix: a tablist the arrow keys move along, each panel named by its tab; outline §4, D23). The chosen tab says
 * so by its weight and a 2 px rule in the accent, its one coloured line (outline §6), never by colour alone. */
export function Tabs<T extends string>({ label, value, onChange, tabs }: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  tabs: { value: T; label: string; content: ReactNode }[];
}) {  // prettier-ignore
  return (
    <TabsPrimitive.Root value={value} onValueChange={(v) => onChange(v as T)} className="flex min-w-0 flex-col gap-4">
      <TabsPrimitive.List aria-label={label} className="flex gap-1 border-b border-line">
        {tabs.map((t) => (
          <TabsPrimitive.Trigger
            key={t.value}
            value={t.value}
            className="-mb-px min-h-11 border-b-2 border-transparent px-3 text-body text-muted hover:text-ink data-[state=active]:border-accent data-[state=active]:font-semibold data-[state=active]:text-ink"
          >
            {t.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {tabs.map((t) => (
        <TabsPrimitive.Content key={t.value} value={t.value} className="flex min-w-0 flex-col gap-5">
          {t.content}
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  );
}
