// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

function Host({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <ConfirmDialog
      open={open}
      title="Remove a member"
      confirmLabel="Remove"
      onConfirm={() => {
        onConfirm();
        setOpen(false); // the caller closes it once its action is done
      }}
      onCancel={() => {
        onCancel();
        setOpen(false);
      }}
    >
      ed@corp.test loses access.
    </ConfirmDialog>
  );
}

it("starts on Cancel, the safe choice", () => {
  render(<Host onConfirm={vi.fn()} onCancel={vi.fn()} />);
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
});

it("never reports a cancel when the caller closes it after confirming", async () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(<Host onConfirm={onConfirm} onCancel={onCancel} />);
  await userEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(onConfirm).toHaveBeenCalledOnce();
  expect(onCancel).not.toHaveBeenCalled();
});

it("holds while its action runs: Escape is refused and Cancel is off", () => {
  const onCancel = vi.fn();
  render(
    <ConfirmDialog open busy title="Remove a member" confirmLabel="Remove" onConfirm={vi.fn()} onCancel={onCancel}>
      ed@corp.test loses access.
    </ConfirmDialog>,
  );
  const escape = new Event("cancel", { cancelable: true }); // what the browser fires on Escape, before closing
  screen.getByRole("dialog").dispatchEvent(escape);
  expect(escape.defaultPrevented).toBe(true);
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveProperty("disabled", true);
  expect(onCancel).not.toHaveBeenCalled();
});

it("lets Escape cancel when nothing runs", () => {
  render(
    <ConfirmDialog open title="Remove a member" confirmLabel="Remove" onConfirm={vi.fn()} onCancel={vi.fn()}>
      ed@corp.test loses access.
    </ConfirmDialog>,
  );
  const escape = new Event("cancel", { cancelable: true });
  screen.getByRole("dialog").dispatchEvent(escape);
  expect(escape.defaultPrevented).toBe(false);
});

it("names its cancel when asked", () => {
  render(
    <ConfirmDialog open title="Your latest changes aren't saved" confirmLabel="Leave without saving" cancelLabel="Stay" onConfirm={vi.fn()} onCancel={vi.fn()}>
      They couldn&apos;t be saved.
    </ConfirmDialog>,
  );
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Stay" }));
});
