// SPDX-License-Identifier: Apache-2.0
// The editor's toolbar under the shell's header (4b ruling 19): the way back, the workflow's name, then its state
// and actions (Tasks 13-15 add them).
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

export function Toolbar({ tenantId, name, children }: { tenantId: string; name: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
      <nav aria-label="Breadcrumb">
        <Link to="/t/$tenantId/workflows" params={{ tenantId }} className="text-body text-muted hover:text-ink">
          Workflows
        </Link>
      </nav>
      <span aria-hidden="true" className="text-muted">/</span>
      <h1 className="min-w-0 truncate text-body-lg font-semibold">{name}</h1>
      <div className="grow" />
      {children}
    </div>
  );
}
