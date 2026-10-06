// SPDX-License-Identifier: Apache-2.0
// "Connect to an existing step" (4b ruling 14): the steps that may follow a port, never itself, a step already
// connected from it, or one that would close a loop. The keyboard's and a single pointer's way to what a drag from
// a handle does. A native modal dialog (D23).
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import { canConnect, nodesOf, type PortRef } from "../../lib/graph";
import type { GraphDoc, NodeType } from "../../lib/workflows";

export function ConnectDialog({
  doc, types, from, onConnect, onClose,
}: { doc: GraphDoc; types: Map<string, NodeType>; from: PortRef; onConnect: (to: string) => void; onClose: () => void }) {  // prettier-ignore
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLButtonElement>("li button")?.focus();
    }
  }, []);
  const source = nodesOf(doc).find((n) => n.id === from.node);
  const candidates = nodesOf(doc).filter((n) => canConnect(doc, from, n.id)).sort((a, b) => a.key.localeCompare(b.key));
  const name = `${source?.key ?? "a step"}${from.port === "out" ? "" : ` (${from.port})`}`;
  return (
    <dialog
      ref={dialog}
      aria-label={`Connect ${name} to`}
      onClose={onClose}
      className="mx-auto mt-20 w-[480px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <h2 className="text-h3 font-semibold">Connect {name} to</h2>
      {candidates.length === 0 ? (
        <p className="mt-3 text-body text-muted">No step can follow it: each is itself, already connected, or would close a loop.</p>
      ) : (
        <ul className="mt-3 flex max-h-80 flex-col gap-1 overflow-y-auto">
          {candidates.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => {
                  dialog.current?.close();
                  onConnect(n.id);
                }}
                className="flex w-full items-baseline justify-between gap-3 rounded-md px-3 py-2 text-left hover:bg-surface-hover"
              >
                <span className="font-medium">{n.key}</span>
                <span className="text-small text-muted">{types.get(n.type)?.title ?? n.type}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-6 flex justify-end">
        <Button onClick={() => dialog.current?.close()}>Cancel</Button>
      </div>
    </dialog>
  );
}
