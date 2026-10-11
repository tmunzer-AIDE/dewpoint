// SPDX-License-Identifier: Apache-2.0
// The Triggers panel (4c-3b; the mockups' Main, ReadOnly and Narrow boards): what starts the workflow, opened from the
// start card. Its input is the draft's, saved with it and used once published (Task 9 adds its live schedules, Task 11
// its webhooks). A viewer or an operator sees it all, read only.
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
import { SIDE } from "../side";
import { TriggersContext, type Triggers } from "./context";
import { InputSection, type FocusAt } from "./InputSection";

export function TriggersPanel({ value, focusAt, onClose }: { value: Triggers; focusAt: FocusAt; onClose: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!focusAt) heading.current?.focus();
  }, [focusAt]);
  return (
    <TriggersContext.Provider value={value}>
      <aside
        aria-labelledby="triggers-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
        }}
        className={`${SIDE} gap-6`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col">
            <h2 id="triggers-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold outline-none">Triggers</h2>
            <span className="truncate text-small text-muted">How {value.name} starts</span>
          </div>
          <Button size="sm" onClick={onClose}>Close</Button>
        </div>
        {value.viewer && <p className="text-small text-muted">You can see this workflow&apos;s triggers; changing them needs the editor role.</p>}
        <InputSection focusAt={focusAt} />
      </aside>
    </TriggersContext.Provider>
  );
}
