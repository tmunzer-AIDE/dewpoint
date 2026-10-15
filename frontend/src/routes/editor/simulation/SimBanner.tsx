// SPDX-License-Identifier: Apache-2.0
// What a simulation is, said wherever one is started or shown (D2, D3; §7.1, §7.3): slate with the hatch, never live
// orange. The hatch sits only behind slate text (`text-sim`), which holds 4.5:1 over it.
import type { ReactNode } from "react";

export function SimBanner({ children, role }: { children: ReactNode; role?: "status" }) {
  return (
    <div role={role} className="hatch-sim flex flex-col gap-1.5 rounded-lg border border-sim bg-sim-bg px-3 py-2 text-small text-sim">
      {children}
    </div>
  );
}
