// SPDX-License-Identifier: Apache-2.0
// The design's table (screens 1a, 1i): a rounded frame, a surface-2 head in small muted type, a hairline per row.
import type { ReactNode, TdHTMLAttributes } from "react";

export function Table({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <table className={`w-full border-separate border-spacing-0 overflow-hidden rounded-lg border border-line bg-surface text-body ${className}`}>
      {children}
    </table>
  );
}

export function Th({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <th scope="col" className={`bg-surface-2 px-3 py-2.5 text-left text-small font-medium text-muted ${className}`}>{children}</th>;
}

export function Td({ children, className = "", ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...rest} className={`border-t border-line px-3 py-2.5 ${className}`}>{children}</td>;
}
