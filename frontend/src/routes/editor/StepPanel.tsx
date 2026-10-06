// SPDX-License-Identifier: Apache-2.0
// A step's panel (Enter on a step; 4b ruling 15): what the step is and how it runs, its problems and its
// expressions, and, for an editor, where it sits: placed with a click on the canvas or moved 20 px a click (WCAG
// 2.5.7, ruling 13 amended). Its config is read-only in 4b: 4c's drawer replaces it with Setup and Options. Escape
// closes it and gives focus back to the step.
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../lib/workflows";

const EFFECTS: Record<NodeType["side_effect"], string> = {
  none: "Changes nothing",
  idempotent: "Changes things; safe to repeat",
  keyed: "Changes things once per key",
  reconcilable: "Changes things; checked before a retry",
  ambiguous: "Changes things; a retry may repeat it",
};

export type Nudge = "ArrowLeft" | "ArrowUp" | "ArrowDown" | "ArrowRight";
const NUDGES: { key: Nudge; glyph: string; word: string }[] = [
  { key: "ArrowLeft", glyph: "←", word: "left" },
  { key: "ArrowUp", glyph: "↑", word: "up" },
  { key: "ArrowDown", glyph: "↓", word: "down" },
  { key: "ArrowRight", glyph: "→", word: "right" },
];

export function StepPanel({
  node, type, ports, problems, expressions, editable, onDelete, onConnectPort, onPlace, onNudge, onClose,
}: {
  node: GraphNode; type: NodeType | undefined; ports: string[]; problems: Diagnostic[] | null; expressions: Expression[];
  editable: boolean; onDelete: () => void; onConnectPort: (port: string) => void; onPlace: () => void;
  onNudge: (key: Nudge) => void; onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [node.id]);
  return (
    <aside
      aria-labelledby="step-panel-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="flex w-full max-w-[440px] shrink-0 flex-col gap-5 overflow-y-auto border-l border-line bg-surface p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="step-panel-title" ref={heading} tabIndex={-1} className="truncate font-mono text-body-lg font-semibold">
            {node.key}
          </h2>
          <p className="text-small text-muted">{type ? `${type.title} · ${type.ref}` : `Unknown step type ${node.type}`}</p>
        </div>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {type && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-small">
          <dt className="text-muted">Runs</dt>
          <dd>{type.kind === "control" ? "In the engine" : "As its own step"}</dd>
          {type.kind === "action" && (<><dt className="text-muted">Effect</dt><dd>{EFFECTS[type.side_effect]}</dd></>)}
          <dt className="text-muted">Retries</dt>
          <dd>Up to {node.options?.max_attempts ?? type.retry.max_attempts} attempts</dd>
          <dt className="text-muted">Timeout</dt>
          <dd>{node.options?.timeout_s ?? type.timeout_s} s</dd>
        </dl>
      )}
      <section className="flex flex-col gap-2">
        <h3 className="text-small font-semibold">Problems</h3>
        {problems === null ? (
          <p className="text-small text-muted">Not checked for what&apos;s on the screen.</p>
        ) : problems.length === 0 ? (
          <p className="text-small text-muted">None found in the saved draft.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {problems.map((d, i) => (
              <li key={`${d.code}:${d.field}:${i}`} className="text-small">
                <span className={d.severity === "error" ? "text-danger" : "text-warn-ink"}>{d.message}</span>
                {d.fix && <span className="block text-muted">{d.fix}</span>}
                <span className="block font-mono text-meta text-muted">{d.code}{d.field ? ` · ${d.field}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {expressions.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-small font-semibold">Expressions</h3>
          <ul className="flex flex-col gap-1.5 text-small">
            {expressions.map((x) => (
              <li key={x.field}>
                <span className="font-mono text-meta">{x.field}</span>{" "}
                {x.mode === "local" ? "Runs inline" : `Runs as a separate step: ${x.reason ?? "no reason given"}`}
              </li>
            ))}
          </ul>
        </section>
      )}
      {editable && (
        <div role="group" aria-label={`Where ${node.key} sits`} className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={onPlace}>Place on the canvas…</Button>
          {NUDGES.map((n) => (
            <Button key={n.key} size="sm" aria-label={`Move ${node.key} ${n.word}`} onClick={() => onNudge(n.key)}>
              {n.glyph}
            </Button>
          ))}
        </div>
      )}
      {editable && (
        <div className="flex flex-wrap gap-2">
          {ports.map((port) => (
            <Button key={port} size="sm" onClick={() => onConnectPort(port)}>
              Connect {port === "out" ? "" : `${port} `}to…
            </Button>
          ))}
          <Button size="sm" variant="danger-outline" onClick={onDelete}>Delete step</Button>
        </div>
      )}
    </aside>
  );
}
