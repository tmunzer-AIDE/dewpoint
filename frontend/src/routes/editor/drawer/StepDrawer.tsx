// SPDX-License-Identifier: Apache-2.0
// A step's drawer (4c-1, §10.3; it replaces 4b's panel, ruling 2). At the top: its key, its type, how it runs and what
// a failure does. Then the problems that belong to no field. Then its settings on two tabs, generated from its type's
// schema, the required ones on Setup and the rest on Options (ruling 3). Then how its formulas run, and, for an
// editor, 4b's actions: its "+" twins (WCAG 2.5.8), where it sits (2.5.7), its edges. Escape closes it and gives focus
// back to the step. What its fields do to the draft goes through `actions`, the editor's (ruling 18).
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Tabs } from "../../../components/Tabs";
import { fieldsOf, tabsOf, type FieldSpec } from "../../../lib/schemaForm";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";
import type { ItemAction } from "../items";
import { SIDE } from "../side";
import { DrawerContext, problemsAt, segment, type DrawerActions } from "./context";
import { ErrorHandling, chipText } from "./ErrorHandling";
import { FieldView } from "./FieldView";

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

type Tab = "setup" | "options";

/** How many of the problems fall in these fields: a tab's count (ruling 3). */
const counted = (problems: Diagnostic[], fields: FieldSpec[]) =>
  problems.filter((d) => {
    const field = d.field;
    return field !== null && fields.some((f) => field === f.pointer || field.startsWith(`${f.pointer}/`));
  }).length;
const tabLabel = (label: string, n: number) => (n === 0 ? label : `${label} · ${n} ${n === 1 ? "problem" : "problems"}`);

export function StepDrawer({
  node, type, tenantId, workflowId, ports, problems, expressions, editable, adds, actions,
  onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
}: {
  node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; ports: string[];
  problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
  actions: DrawerActions; onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
  onPlace: () => void; onNudge: (key: Nudge) => void; onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [node.id]);
  const fields = useMemo(() => (type ? fieldsOf(type) : []), [type]);
  const { setup, options } = tabsOf(fields);
  const [tab, setTab] = useState<Tab>(setup.length > 0 ? "setup" : "options");
  const [handling, setHandling] = useState(false);
  const mine = problems ?? [];
  const top = new Set(fields.map((f) => segment(f.name)));
  // A problem no field shows: about the step as a whole, or a part its schema doesn't name (ruling 16).
  const general = mine.filter((d) => d.field === null || problemsAt([d], "", top).length > 0);
  const drawer = { ...actions, node, type, editable, tenantId, workflowId, problems: mine, expressions };
  return (
    <DrawerContext.Provider value={drawer}>
      <aside
        aria-labelledby="step-drawer-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
        }}
        className={`${SIDE} gap-5`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id="step-drawer-title" ref={heading} tabIndex={-1} className="truncate font-mono text-body-lg font-semibold">
              {node.key}
            </h2>
            <p className="text-small text-muted">{type ? `${type.title} · ${type.ref}` : `Unknown step type ${node.type}`}</p>
            {type && (
              <p className="text-small text-muted">
                {type.kind === "control" ? "Runs in the engine" : `Runs as its own step · ${EFFECTS[type.side_effect]}`}
              </p>
            )}
            {type ? (
              <Button size="sm" className="self-start" aria-expanded={handling} aria-controls="error-handling" onClick={() => setHandling(!handling)}>
                {chipText(node, type)}
              </Button>
            ) : (
              <p className="text-small">{chipText(node, type)}</p>
            )}
          </div>
          <Button size="sm" onClick={onClose}>Close</Button>
        </div>
        {handling && <ErrorHandling />}
        {problems === null ? (
          <p className="text-small text-muted">Not checked for what&apos;s on the screen.</p>
        ) : (
          general.length > 0 && (
            <section aria-labelledby="step-problems" className="flex flex-col gap-1.5">
              <h3 id="step-problems" tabIndex={-1} className="text-small font-semibold">Problems with this step</h3>
              <ul className="flex flex-col gap-1.5">
                {general.map((d, i) => (
                  <li key={`${d.code}:${d.field}:${i}`} className="text-small">
                    <span className={d.severity === "error" ? "text-danger" : "text-warn-ink"}>{d.message}</span>
                    {d.fix && <span className="block text-muted">{d.fix}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )
        )}
        {!type ? (
          <p className="text-small">
            This server doesn&apos;t know this step&apos;s type, so its settings can&apos;t be shown. They&apos;re kept as they are.
          </p>
        ) : fields.length === 0 ? (
          <p className="text-small text-muted">This step has nothing to set up.</p>
        ) : (
          <Tabs
            label="Settings"
            value={tab}
            onChange={setTab}
            tabs={[
              {
                value: "setup",
                label: tabLabel("Setup", counted(mine, setup)),
                content: setup.length > 0 ? (
                  <>
                    <p className="text-small text-muted">Each of these is required.</p>
                    {setup.map((f) => <FieldView key={f.pointer} spec={f} />)}
                  </>
                ) : (
                  <p className="text-small text-muted">Nothing here is required.</p>
                ),
              },
              {
                value: "options",
                label: tabLabel("Options", counted(mine, options)),
                content: options.length > 0
                  ? options.map((f) => <FieldView key={f.pointer} spec={f} />)
                  : <p className="text-small text-muted">Nothing else to set.</p>,
              },
            ]}
          />
        )}
        {expressions.length > 0 && (
          <section className="flex flex-col gap-2">
            <h3 className="text-small font-semibold">How its formulas run</h3>
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
        {editable && adds.length > 0 && (
          // Each "+" this step has on the canvas, at full size whatever the zoom (WCAG 2.5.8: their equivalents).
          <div role="group" aria-label="Add a step" className="flex flex-col items-start gap-2">
            {adds.map((a) => (
              <Button key={a.label} size="sm" onClick={() => onAdd(a.action)}>{a.label}</Button>
            ))}
          </div>
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
    </DrawerContext.Provider>
  );
}
