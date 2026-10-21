// SPDX-License-Identifier: Apache-2.0
// Choosing a step's type (`A`, and every "+"): a native modal dialog around cmdk, as the palette (D23). Only active
// types: a deprecated one stays drawn where it's used, but new versions shouldn't add it. Mid-edge, only types that
// continue the flow (4b ruling 10). A plugin's steps in groups show as their groups (4f-2, the Mist step design §5.1:
// Mist as its 85 resources, not its 294 steps); a group chosen lists its steps, and Back (or Backspace in the empty
// search) returns. What's shown is filtered here, not by cmdk: a group, and a grouped step, match by their own rules.
import { useQuery } from "@tanstack/react-query";
import { Command, defaultFilter } from "cmdk";
import { Fragment, useEffect, useRef, useState } from "react";
import { Button } from "../../components/Button";
import { PALETTE_GROUP, PALETTE_ITEM } from "../../components/CommandPalette";
import { continuationPort, type PortRef } from "../../lib/graph";
import { actionWords, groupMatches, grouped, stepMatches, type StepGroup } from "../../lib/stepGroups";
import type { GraphEdge, NodeType } from "../../lib/workflows";
import { connectionTypesQuery } from "./drawer/pickers";

export type PickMode = { kind: "after"; from: PortRef | null } | { kind: "insert"; edge: GraphEdge } | { kind: "before"; entry: string };

const EFFECTS: Record<NodeType["side_effect"], string> = {
  none: "Changes nothing",
  idempotent: "Changes things; safe to repeat",
  keyed: "Changes things once per key",
  reconcilable: "Changes things; checked before a retry",
  ambiguous: "Changes things; a retry may repeat it",
};

/** cmdk's own search, for what no group holds: its score, best first; nothing typed keeps the order given. */
function ranked(types: NodeType[], query: string): NodeType[] {
  if (query.trim() === "") return types;
  return types
    .map((type, i) => ({ type, i, score: defaultFilter(`${type.title} ${type.ref}`, query) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.i - b.i)
    .map((x) => x.type);
}

function Choice({ type, labels, onSelect }: { type: NodeType; labels: ReadonlyMap<string, string>; onSelect: () => void }) {
  return (
    <Command.Item value={type.ref} onSelect={onSelect} className={`${PALETTE_ITEM} flex-col items-start`}>
      {/* At 320 px its ref goes under its title. */}
      <span className="flex w-full flex-wrap items-baseline justify-between gap-x-3">
        <span className="font-medium">{type.title}</span>
        <span className="font-mono text-meta text-muted">{type.ref}</span>
      </span>
      {type.description && <span className="text-small text-muted">{type.description}</span>}
      {type.kind === "action" && (
        <span className="text-small text-muted">
          {EFFECTS[type.side_effect]}
          {/* Named by its label ("Mist"), never its key (4f-2, as 4f-1's connection words). */}
          {type.credentials.map((c) => `. Uses a ${labels.get(c) ?? c} connection`).join("")}
        </span>
      )}
    </Command.Item>
  );
}

function GroupChoice({ group, onSelect }: { group: StepGroup; onSelect: () => void }) {
  const count = group.types.length === 1 ? "1 action" : `${group.types.length} actions`;
  return (
    <Command.Item value={`group ${group.plugin} ${group.title}`} onSelect={onSelect} className={`${PALETTE_ITEM} flex-col items-start`}>
      <span className="flex w-full items-baseline justify-between gap-3">
        <span className="font-medium">{group.title}</span>
        <span className="font-mono text-meta text-muted">{count}</span>
      </span>
      <span className="text-small text-muted">{actionWords(group)}</span>
    </Command.Item>
  );
}

export function StepPicker({
  mode, types, onPick, onConnect, onClose,
}: { mode: PickMode; types: NodeType[]; onPick: (type: NodeType) => void; onConnect?: () => void; onClose: () => void }) {  // prettier-ignore
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<StepGroup | null>(null);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      input.current?.focus();
    }
  }, []);
  const continuing = mode.kind !== "after";
  const offered = types.filter((t) => t.state === "active" && (!continuing || continuationPort(t) !== null));
  const { plugins, loose } = grouped(offered);
  const takes = offered.some((t) => t.credentials.length > 0);
  const kinds = useQuery({ ...connectionTypesQuery(), enabled: takes });
  const labels = new Map((kinds.data ?? []).map((k) => [k.key, k.label]));
  const pick = (type: NodeType) => {
    dialog.current?.close();
    onPick(type);
  };
  const enter = (group: StepGroup) => {
    setOpen(group);
    setQuery("");
    setSelected("");
    input.current?.focus();
  };
  const back = () => {
    if (open !== null) setSelected(`group ${open.plugin} ${open.title}`);
    setOpen(null);
    setQuery("");
    input.current?.focus();
  };
  const typed = query.trim() !== "";
  const flow = ranked(loose.filter((t) => t.kind === "control"), query);
  const actions = ranked(loose.filter((t) => t.kind === "action"), query);
  const plural = plugins.map((p) => p.plugin).join(" or ");
  return (
    <dialog
      ref={dialog}
      aria-label={open ? `Add a step: ${open.title}` : "Add a step"}
      onClose={onClose}
      className="mx-auto mt-20 w-[560px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <Command label="Add a step" loop shouldFilter={false} value={selected} onValueChange={setSelected}>
        {open && (
          <div className="flex items-center gap-3 border-b border-line px-3 py-2">
            <Button size="sm" aria-label="Back to every step" className="max-sm:min-h-[44px]" onClick={back}>← Back</Button>
            <span className="text-small">
              {open.plugin} · <strong className="font-semibold">{open.title}</strong>
            </span>
          </div>
        )}
        <Command.Input
          ref={input}
          value={query}
          onValueChange={setQuery}
          onKeyDown={(e) => {
            if (e.key === "Backspace" && query === "" && open !== null) {
              e.preventDefault();
              back();
            }
          }}
          placeholder={open ? "Type an action's name" : plugins.length > 0 ? `Type a step's name or a ${plural} resource` : "Type a step's name"}
          className="w-full border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2 [&:first-child]:rounded-t-dialog"
        />
        <Command.List className="max-h-96 overflow-y-auto p-1">
          {continuing && <p className="px-3 pt-2 text-small text-muted">Only steps that continue the flow can go here.</p>}
          <Command.Empty className="px-3 py-2 text-body text-muted">No step type matches.</Command.Empty>
          {open ? (
            <Command.Group heading={open.title} className={PALETTE_GROUP}>
              {ranked(open.types, query).map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
            </Command.Group>
          ) : (
            <>
              {flow.length > 0 && (
                <Command.Group heading="Flow" className={PALETTE_GROUP}>
                  {flow.map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
                </Command.Group>
              )}
              {plugins.map(({ plugin, groups }) => {
                const steps = typed ? groups.flatMap((g) => g.types).filter((t) => stepMatches(t, query)).sort((a, b) => a.title.localeCompare(b.title)) : [];
                const found = typed ? groups.filter((g) => groupMatches(g, query)) : groups;
                return (
                  <Fragment key={plugin}>
                    {steps.length > 0 && (
                      <Command.Group heading={steps.length === 1 ? `${plugin} step` : `${plugin} steps`} className={PALETTE_GROUP}>
                        {steps.map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
                      </Command.Group>
                    )}
                    {found.length > 0 && (
                      <Command.Group
                        heading={typed ? `${plugin} resources` : `${plugin}: ${groups.length} resources, type to find one`}
                        className={PALETTE_GROUP}
                      >
                        {found.map((g) => <GroupChoice key={g.title} group={g} onSelect={() => enter(g)} />)}
                      </Command.Group>
                    )}
                  </Fragment>
                );
              })}
              {actions.length > 0 && (
                <Command.Group heading="Actions" className={PALETTE_GROUP}>
                  {actions.map((t) => <Choice key={t.ref} type={t} labels={labels} onSelect={() => pick(t)} />)}
                </Command.Group>
              )}
              {mode.kind === "after" && mode.from && onConnect && (!typed || defaultFilter("Connect to an existing step…", query) > 0) && (
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
            </>
          )}
        </Command.List>
      </Command>
    </dialog>
  );
}
