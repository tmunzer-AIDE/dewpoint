// SPDX-License-Identifier: Apache-2.0
// A confirmation for an action that can't be undone: a native modal <dialog> (focus moves in and back, Escape cancels,
// the page behind is inert, no injected styles: D23). Focus starts on Cancel, the safe choice.
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./Button";

export function ConfirmDialog({ open, title, confirmLabel, busy = false, onConfirm, onCancel, children }: {
  open: boolean;
  title: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const closing = useRef(false); // set while the dialog closes because `open` turned false
  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      cancel.current?.focus();
    }
    if (!open && d.open) {
      closing.current = true;
      d.close();
    }
  }, [open]);
  return (
    <dialog
      ref={dialog}
      aria-label={title}
      onClose={() => {
        // Escape closes the dialog itself: that's a cancel. A close the caller asked for (after its confirm) isn't.
        if (closing.current) closing.current = false;
        else onCancel();
      }}
      className="mx-auto mt-24 w-[480px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <h2 className="text-h3 font-semibold">{title}</h2>
      <div className="mt-2 text-body text-muted">{children}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button ref={cancel} onClick={onCancel}>Cancel</Button>
        <Button variant="danger" onClick={onConfirm} disabled={busy}>{confirmLabel}</Button>
      </div>
    </dialog>
  );
}
