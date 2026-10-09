// SPDX-License-Identifier: Apache-2.0
// Every edit typed but not applied, in one place (4c-1, ruling 18): its step and field, its text as typed, why it isn't
// applied, and the person's choices: go to it, while its step is in the draft, or discard it. An edit whose field is
// gone (an undo removed its item, or its step) is read and discarded here, never by recreating what was removed (the
// review of revision 4). Its text is the person's own: a sensitive field takes formulas only, and no value holding a
// sensitive part is edited as JSON, so no secret is shown.
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import type { Unapplied } from "../../lib/unapplied";
import { SIDE } from "./side";

export function UnappliedPanel({ edits, keyOf, reason, onGo, onDiscard, onDownload, onClose }: {
  edits: Unapplied[]; keyOf: (node: string) => string | null; reason: (u: Unapplied) => string;
  onGo: (u: Unapplied) => void; onDiscard: (u: Unapplied) => void; onDownload: () => void; onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  return (
    <aside
      aria-labelledby="unapplied-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className={`${SIDE} gap-5`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="unapplied-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Edits not applied</h2>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {edits.length === 0 ? (
        <p className="text-small text-muted">None: everything typed is in the draft.</p>
      ) : (
        <ul>
          {edits.map((u) => {
            const step = keyOf(u.node);
            const where = `${step ?? "A step no longer in the draft"} · ${u.label}`;
            return (
              <li key={u.id} className="flex flex-col gap-1.5 border-t border-line py-2.5 text-small first:border-t-0">
                <span className="font-semibold">{where}</span>
                <pre className="whitespace-pre-wrap break-all rounded-lg border border-line px-3 py-2 font-mono text-small">
                  {u.text === "" ? "(empty)" : u.text}
                </pre>
                <span className="text-muted">{reason(u)}</span>
                <span className="flex flex-wrap gap-2">
                  {step !== null && <Button size="sm" aria-label={`Go to it: ${where}`} onClick={() => onGo(u)}>Go to it</Button>}
                  <Button size="sm" variant="danger-outline" aria-label={`Discard: ${where}`} onClick={() => onDiscard(u)}>Discard</Button>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {edits.length > 0 && (
        <Button size="sm" className="self-start" onClick={onDownload}>Download them</Button>
      )}
    </aside>
  );
}
