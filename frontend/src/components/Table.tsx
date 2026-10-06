// SPDX-License-Identifier: Apache-2.0
// The design's table (screens 1a, 1i): a rounded frame, a surface-2 head in small muted type, a hairline per row.
import type { ReactNode, TdHTMLAttributes } from "react";

/** A narrow screen scrolls the table inside its frame, never the page (WCAG 1.4.10). */
export function Table({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`max-w-full overflow-x-auto rounded-lg border border-line ${className}`}>
      <table className="w-full border-separate border-spacing-0 bg-surface text-body">{children}</table>
    </div>
  );
}

export function Th({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <th scope="col" className={`bg-surface-2 px-3 py-2.5 text-left text-small font-medium text-muted ${className}`}>{children}</th>;
}

export function Td({ children, className = "", ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...rest} className={`border-t border-line px-3 py-2.5 ${className}`}>{children}</td>;
}
