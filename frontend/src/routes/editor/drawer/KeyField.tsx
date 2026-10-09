// SPDX-License-Identifier: Apache-2.0
// A step's key renamed from its drawer (4c-1, ruling 11). It's checked before it's written: a key the graph's format
// refuses isn't saved, and a CEL word or another step's key never reads. Every structured reference follows. What's
// typed is an unapplied edit (ruling 18): kept while the drawer closes, disabled while the draft can't change, and
// said, never as if it had worked, when it's refused.
import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Field } from "../../../components/Field";
import { useDrawer } from "./context";

export function KeyField({ onRenamed }: { onRenamed: () => void }) {
  const drawer = useDrawer();
  const held = drawer.held("key", "");
  const [open, setOpen] = useState(held !== undefined); // a rename typed before the drawer closed is still open
  const box = useRef<HTMLDivElement>(null); // Field makes its own input: focus finds it here
  const opener = useRef<HTMLButtonElement>(null);
  const current = drawer.node.key;
  const disabled = !drawer.editable;
  useEffect(() => {
    if (open) box.current?.querySelector("input")?.focus();
  }, [open]);
  const close = () => {
    drawer.release("key", ""); // Cancel, Escape: dropped, on purpose
    setOpen(false);
    requestAnimationFrame(() => opener.current?.focus());
  };
  const apply = () => {
    if (disabled) return;
    if (!held || held.text.trim() === current) return close();
    // Rename is the person's explicit act on the step as it is now, whatever the key was when they began typing.
    drawer.rebase("key", "");
    if (drawer.apply("key", "") !== null) return; // refused: its reason shows at the field, never as done
    setOpen(false);
    onRenamed();
  };
  if (!open) {
    return drawer.editable ? (
      <Button ref={opener} size="sm" className="self-start" onClick={() => setOpen(true)}>Rename</Button>
    ) : null;
  }
  return (
    <div
      ref={box}
      className="flex flex-col gap-2"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // closes the rename, not the drawer
          close();
        }
      }}
    >
      <Field
        label="Key" value={held?.text ?? current} disabled={disabled} spellCheck={false} autoCapitalize="off"
        error={held?.why ?? undefined}
        onChange={(e) => {
          if (e.target.value === current) drawer.release("key", "");
          else drawer.hold("key", "", { path: [], label: "Key", text: e.target.value, why: null });
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") apply();
        }}
      />
      <div className="flex gap-2">
        <Button size="sm" variant="primary" disabled={disabled} onClick={apply}>Rename</Button>
        <Button size="sm" disabled={disabled} onClick={close}>Cancel</Button>
      </div>
    </div>
  );  // prettier-ignore
}
