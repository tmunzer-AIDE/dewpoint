// SPDX-License-Identifier: Apache-2.0
// A workflow's versions (B4a; 4b ruling 17): each viewable read-only, and, for a publisher, made active. The active
// one is marked in words; a version that can't run says what blocks it.
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import { since, type VersionRow } from "../../lib/workflows";
import { SIDE } from "./side";

export function VersionsPanel({
  versions, publisher, onView, onActivate, onClose,
}: {
  versions: VersionRow[]; publisher: boolean; onView: (v: VersionRow) => void; onActivate: (v: VersionRow) => void;
  onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  return (
    <aside
      aria-labelledby="versions-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className={`${SIDE} gap-4`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="versions-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Versions</h2>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {versions.length === 0 ? (
        <p className="text-small text-muted">Nothing is published yet.</p>
      ) : (
        <ul className="flex flex-col">
          {versions.map((v) => (
            <li key={v.id} className="flex flex-col gap-1.5 border-t border-line py-3 first:border-t-0">
              <span className="flex flex-wrap items-baseline gap-2">
                <span className="font-semibold">Version {v.number}</span>
                {v.active && <span className="rounded-sm border border-accent px-1.5 text-meta text-accent-ink">Active</span>}
                <span className="text-small text-muted">published {since(v.published_at)}</span>
              </span>
              {!v.executable && <span className="text-small text-danger">Can&apos;t run: {v.blocked_by.join(", ")}</span>}
              <span className="flex flex-wrap gap-2">
                <Button size="sm" aria-label={`View version ${v.number}`} onClick={() => onView(v)}>View</Button>
                {publisher && !v.active && (
                  <Button size="sm" aria-label={`Make version ${v.number} active`} onClick={() => onActivate(v)}>
                    Make active
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
