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
