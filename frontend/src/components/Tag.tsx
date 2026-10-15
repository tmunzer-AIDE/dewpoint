// SPDX-License-Identifier: Apache-2.0
// A word beside a label (4d-1c; the InputFields and TestTab boards): what a field is, said in words, never colour
// alone (§7.4). Small, muted and outlined: data about the field, not a button.
import type { ReactNode } from "react";

export function Tag({ children }: { children: ReactNode }) {
  return <span className="ms-1.5 rounded-sm border border-line-strong px-1.5 text-meta font-normal text-muted">{children}</span>;
}
