// SPDX-License-Identifier: Apache-2.0
// Choosing a step's type (`A`, and every "+"): a native modal dialog around cmdk, as the palette (D23). Only active
// types: a deprecated one stays drawn where it's used, but new versions shouldn't add it. Mid-edge, only types that
// continue the flow (4b ruling 10).
import { Command } from "cmdk";
import { useEffect, useRef } from "react";
import { PALETTE_GROUP, PALETTE_ITEM } from "../../components/CommandPalette";
import { continuationPort, type PortRef } from "../../lib/graph";
import type { GraphEdge, NodeType } from "../../lib/workflows";

export type PickMode = { kind: "after"; from: PortRef | null } | { kind: "insert"; edge: GraphEdge } | { kind: "before"; entry: string };

const EFFECTS: Record<NodeType["side_effect"], string> = {
  none: "Changes nothing",
  idempotent: "Changes things; safe to repeat",
  keyed: "Changes things once per key",
  reconcilable: "Changes things; checked before a retry",
  ambiguous: "Changes things; a retry may repeat it",
};

function Choice({ type, onSelect }: { type: NodeType; onSelect: () => void }) {
  return (
    <Command.Item value={`${type.title} ${type.ref}`} onSelect={onSelect} className={`${PALETTE_ITEM} flex-col items-start`}>
      <span className="flex w-full items-baseline justify-between gap-3">
        <span className="font-medium">{type.title}</span>
        <span className="font-mono text-meta text-muted">{type.ref}</span>
      </span>
      {type.description && <span className="text-small text-muted">{type.description}</span>}
      {type.kind === "action" && (
        <span className="text-small text-muted">
          {EFFECTS[type.side_effect]}
          {type.credentials.map((c) => `. Uses a ${c} connection`).join("")}
        </span>
      )}
    </Command.Item>
  );
}

export function StepPicker({
  mode, types, onPick, onConnect, onClose,
}: { mode: PickMode; types: NodeType[]; onPick: (type: NodeType) => void; onConnect?: () => void; onClose: () => void }) {  // prettier-ignore
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("[cmdk-input]")?.focus();
    }
  }, []);
  const continuing = mode.kind !== "after";
  const offered = types.filter((t) => t.state === "active" && (!continuing || continuationPort(t) !== null));
  const pick = (type: NodeType) => {
    dialog.current?.close();
    onPick(type);
  };
  return (
    <dialog
      ref={dialog}
      aria-label="Add a step"
      onClose={onClose}
      className="mx-auto mt-20 w-[560px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <Command label="Add a step" loop>
        <Command.Input
          placeholder="Type a step's name"
          className="w-full rounded-t-dialog border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2"
        />
        <Command.List className="max-h-96 overflow-y-auto p-1">
          {continuing && <p className="px-3 pt-2 text-small text-muted">Only steps that continue the flow can go here.</p>}
          <Command.Empty className="px-3 py-2 text-body text-muted">No step type matches.</Command.Empty>
          {offered.some((t) => t.kind === "control") && (
            <Command.Group heading="Flow" className={PALETTE_GROUP}>
              {offered.filter((t) => t.kind === "control").map((t) => <Choice key={t.ref} type={t} onSelect={() => pick(t)} />)}
            </Command.Group>
          )}
          {offered.some((t) => t.kind === "action") && (
            <Command.Group heading="Actions" className={PALETTE_GROUP}>
              {offered.filter((t) => t.kind === "action").map((t) => <Choice key={t.ref} type={t} onSelect={() => pick(t)} />)}
            </Command.Group>
          )}
          {mode.kind === "after" && mode.from && onConnect && (
            <Command.Group heading="Or" className={PALETTE_GROUP}>
              <Command.Item
                value="Connect to an existing step…"
                className={PALETTE_ITEM}
                onSelect={() => {
                  dialog.current?.close();
                  onConnect();
                }}
              >
                Connect to an existing step…
              </Command.Item>
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </dialog>
  );
}
