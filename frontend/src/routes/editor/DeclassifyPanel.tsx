// SPDX-License-Identifier: Apache-2.0
// Declassify (4c-2b, the mockups' declassify board; engine 2b spec §4.1, §4.3): the workflow's decisions that read
// sensitive data, which make something visible in a run's history, and the ones listed as acceptable. Nothing is listed
// for the person: each is chosen, with what it reveals said first, as the server says it. A draft keeps its entries;
// publishing them needs `workflow.declassify` (the server answers).
import { useId, useState } from "react";
import { Button } from "../../components/Button";
import { fieldLabel } from "../../lib/schemaForm";
import type { Diagnostic, GraphDoc, NodeType, Validation } from "../../lib/workflows";
import { findNode, sameId } from "../../lib/graph";
import { SIDE } from "./side";

export interface Site {
  node: string;
  field: string;
}

/** A decision the person may declassify: what the server says it makes visible, with a confirmation first. */
function Undecided({ d, label, editable, onGo, onDeclassify }: {
  d: Diagnostic & Site; label: string; editable: boolean; onGo: () => void; onDeclassify: () => void;
}) {  // prettier-ignore
  const [agreed, setAgreed] = useState(false);
  const id = useId();
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-2 rounded-lg border border-line-strong p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-small">{label}</span>
        <Button size="sm" onClick={onGo}>Go to the step</Button>
      </div>
      <p className="text-small">{d.message}</p>
      {editable && (
        <>
          <label htmlFor={id} className="flex items-start gap-2 text-small">
            <input id={id} type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5 size-[16px] accent-accent" />
            What it reveals may be visible in run history, to anyone who can see this workflow&apos;s runs
          </label>
          <div>
            <Button size="sm" disabled={!agreed} onClick={onDeclassify}>Declassify this decision</Button>
          </div>
        </>
      )}
    </div>
  );  // prettier-ignore
}

export function DeclassifyPanel({ doc, types, check, editable, onDeclassify, onRemove, onGo, onClose }: {
  doc: GraphDoc; types: Map<string, NodeType>; check: Validation | null; editable: boolean;
  onDeclassify: (site: Site) => void; onRemove: (index: number) => void; onGo: (site: Site) => void; onClose: () => void;
}) {  // prettier-ignore
  const labelOf = (site: Site): string => {
    const node = findNode(doc, site.node);
    if (!node) return "A step no longer in the draft";
    const type = types.get(node.type);
    return `${node.key} · ${type ? fieldLabel(type, site.field) : site.field}`;
  };
  const undecided = (check?.diagnostics ?? []).filter(
    (d): d is Diagnostic & Site => d.code === "taint.undeclassified" && d.node !== null && d.field !== null,
  );
  const entries = doc.settings?.declassify ?? [];
  const noteOf = (site: Site, index: number): string | null => {
    if (!check) return null;
    const hit = check.taint.declassified.find((x) => sameId(x.node, site.node) && x.field === site.field);
    if (hit) return `Reveals ${hit.reveals}.`;
    return check.diagnostics.find((d) => d.code === "taint.stale_declassify" && d.field === `/settings/declassify/${index}`)?.message ?? null;
  };
  return (
    <aside aria-labelledby="declassify-title" className={`${SIDE} flex flex-col gap-4 overflow-y-auto p-5`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col">
          <h2 id="declassify-title" tabIndex={-1} className="text-body-lg font-semibold outline-none">Declassify</h2>
          <span className="text-small text-muted">Workflow settings</span>
        </div>
        <Button size="md" onClick={onClose}>Close</Button>
      </div>
      <p className="text-small text-muted">
        A decision that reads sensitive data shows something in the run&apos;s history: the branch taken, a loop&apos;s item
        count. List a decision here only when that&apos;s acceptable. Nothing is listed for you.
      </p>
      {check === null ? (
        <p className="text-small text-muted">The decisions that need one show once the draft is checked.</p>
      ) : (
        <section aria-labelledby="declassify-undecided" className="flex flex-col gap-2">
          <h3 id="declassify-undecided" className="text-body font-semibold">Needs your decision · {undecided.length}</h3>
          {undecided.length === 0 && <p className="text-small text-muted">No decision reads sensitive data without being listed.</p>}
          {undecided.map((d) => (
            <Undecided
              key={`${d.node}${d.field}`} d={d} label={labelOf(d)} editable={editable}
              onGo={() => onGo(d)} onDeclassify={() => onDeclassify({ node: d.node, field: d.field })}
            />
          ))}
        </section>
      )}
      <section aria-labelledby="declassify-listed" className="flex flex-col">
        <h3 id="declassify-listed" className="text-body font-semibold">Declassified · {entries.length}</h3>
        {entries.map((e, i) => (
          <div key={`${e.node}${e.field}${i}`} className="flex flex-col gap-1.5 border-t border-line py-2.5 first:border-t-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-small">{labelOf(e)}</span>
              {editable && <Button size="sm" aria-label={`Remove ${labelOf(e)}`} onClick={() => onRemove(i)}>Remove</Button>}
            </div>
            {noteOf(e, i) && <span className="text-small text-muted">{noteOf(e, i)}</span>}
          </div>
        ))}
      </section>
      <p className="text-small text-muted">
        You can save a draft with these entries. Publishing it needs the permission to declassify; without it, Publish says so
        and changes nothing.
      </p>
    </aside>
  );  // prettier-ignore
}
