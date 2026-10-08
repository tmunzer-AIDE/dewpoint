// SPDX-License-Identifier: Apache-2.0
// A confirmation for an action that can't be undone: a native modal <dialog> (focus moves in and back, Escape cancels,
// the page behind is inert, no injected styles: D23). Focus starts on Cancel, the safe choice. A constructive action
// (publish, make active) confirms in the primary colour; focus still starts on Cancel, and goes back there when the
// question changes. While its action runs (`busy`) it holds: Escape is refused and Cancel is off, so a cancel never
// races the action it can't stop.
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./Button";

export function ConfirmDialog({
  open, title, confirmLabel, cancelLabel = "Cancel", tone = "danger", busy = false, onConfirm, onCancel, children,
}: {
  open: boolean;
  tone?: "danger" | "primary";
  title: string;
  confirmLabel: string;
  cancelLabel?: string;
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
  useEffect(() => {
    if (open) cancel.current?.focus(); // a question changed while open is asked afresh: never confirmed by a key meant for the old one
  }, [open, title]);
  return (
    <dialog
      ref={dialog}
      aria-label={title}
      onCancel={(e) => {
        if (busy) e.preventDefault();
      }}
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
        <Button ref={cancel} onClick={onCancel} disabled={busy}>{cancelLabel}</Button>
        <Button variant={tone} onClick={onConfirm} disabled={busy}>{confirmLabel}</Button>
      </div>
    </dialog>
  );
}
