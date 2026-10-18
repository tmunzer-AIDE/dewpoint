// SPDX-License-Identifier: Apache-2.0
// The Runs page's filters (editor 4e-1; the runs design §5.2; the ListStates board): "Label · Value ▾" menus, one
// choice each, a set one outlined in the accent. The workflow is chosen from a list that can be searched: a native
// modal dialog around cmdk, as the palette and the step picker are (D23).
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { PALETTE_ITEM } from "../../components/CommandPalette";
import type { ModeFilter, RunFilters, StartedFilter, StatusFilter, TriggerFilter } from "../../lib/runs";
import { workflowsQuery, type WorkflowRow } from "../../lib/workflows";

/** A choice: its value ("any" for no filter), its word on the button, and on the menu when it says more. */
type Choice<T extends string> = { value: T; word: string; item?: string };

const STATUS: Choice<StatusFilter | "any">[] = [
  { value: "any", word: "Any" },
  { value: "waiting", word: "Waiting", item: "Waiting: queued or starting" },
  { value: "running", word: "Running" },
  { value: "succeeded", word: "Succeeded" },
  { value: "failed", word: "Failed" },
  { value: "deadline_exceeded", word: "Ran out of time" },
  { value: "cancelled", word: "Cancelled" },
  { value: "didnt_start", word: "Didn't start", item: "Didn't start: couldn't start or refused" },
];
// A run from `dewpoint dev` is listed under Any only.
const TRIGGER: Choice<TriggerFilter | "any">[] = [
  { value: "any", word: "Any" },
  { value: "manual", word: "By hand" },
  { value: "rerun", word: "Re-run" },
  { value: "schedule", word: "Schedule" },
  { value: "webhook", word: "Webhook" },
];
const MODE: Choice<ModeFilter>[] = [
  { value: "both", word: "Live and simulated" },
  { value: "live", word: "Live" },
  { value: "simulated", word: "Simulated", item: "Simulated: of a published version" },
  { value: "drafts", word: "Draft simulations", item: "Draft simulations: made in the editor" },
  { value: "everything", word: "Everything" },
];
const STARTED: Choice<StartedFilter>[] = [
  { value: "1h", word: "Last hour" },
  { value: "24h", word: "Last 24 hours" },
  { value: "7d", word: "Last 7 days" },
  { value: "30d", word: "Last 30 days" },
  { value: "all", word: "All kept" },
];

const FILTER = "inline-flex min-h-9 items-center gap-1.5 rounded-lg border bg-surface px-3 text-small whitespace-nowrap hover:bg-surface-hover";
const look = (set: boolean) => `${FILTER} ${set ? "border-accent text-accent-ink" : "border-line-control text-ink"}`;

function Label({ label, value }: { label: string; value: string }) {
  return (
    <>
      {label} · <b className="font-semibold">{value}</b> <span aria-hidden="true">▾</span>
    </>
  );
}

function Menu<T extends string>({ label, choices, value, onChange }: { label: string; choices: Choice<T>[]; value: T; onChange: (v: T) => void }) {
  const current = choices.find((c) => c.value === value) ?? choices[0]!;
  return (
    <Dropdown.Root modal={false}>
      <Dropdown.Trigger className={look(current !== choices[0])}>
        <Label label={label} value={current.word} />
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="start" sideOffset={4} className="min-w-48 rounded-lg border border-line bg-surface p-1 shadow-dialog">
          <Dropdown.RadioGroup value={current.value} onValueChange={(v) => onChange(v as T)}>
            {choices.map((c) => (
              <Dropdown.RadioItem
                key={c.value}
                value={c.value}
                className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
              >
                <span className="w-4">
                  <Dropdown.ItemIndicator>✓</Dropdown.ItemIndicator>
                </span>
                {c.item ?? c.word}
              </Dropdown.RadioItem>
            ))}
          </Dropdown.RadioGroup>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function Chooser({ workflows, value, onPick, onClose }: {
  workflows: WorkflowRow[]; value: string | undefined; onPick: (id: string | undefined) => void; onClose: () => void;
}) {  // prettier-ignore
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("[cmdk-input]")?.focus();
    }
  }, []);
  const pick = (id: string | undefined) => {
    dialog.current?.close();
    onPick(id);
  };
  const chosen = (yes: boolean): ReactNode => (
    <span aria-hidden="true" className="w-4">
      {yes ? "✓" : ""}
    </span>
  );
  return (
    <dialog
      ref={dialog}
      aria-label="Choose a workflow"
      onClose={onClose}
      className="mx-auto mt-20 w-[480px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <Command label="Choose a workflow" loop>
        <Command.Input
          placeholder="Find a workflow"
          className="w-full rounded-t-dialog border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2"
        />
        <Command.List className="max-h-96 overflow-y-auto p-1">
          <Command.Empty className="px-3 py-2 text-body text-muted">No workflow matches.</Command.Empty>
          <Command.Item value="Any" onSelect={() => pick(undefined)} className={`${PALETTE_ITEM} justify-start`}>
            {chosen(value === undefined)}Any
          </Command.Item>
          {workflows.map((w) => (
            <Command.Item key={w.id} value={`${w.name} ${w.id}`} onSelect={() => pick(w.id)} className={`${PALETTE_ITEM} justify-start`}>
              {chosen(value === w.id)}
              {w.name}
            </Command.Item>
          ))}
        </Command.List>
      </Command>
    </dialog>
  );
}

function WorkflowFilter({ tenantId, value, onChange }: { tenantId: string; value: string | undefined; onChange: (id: string | undefined) => void }) {
  const workflows = useQuery(workflowsQuery(tenantId));
  const [open, setOpen] = useState(false);
  const name = value === undefined ? "Any" : (workflows.data?.find((w) => w.id === value)?.name ?? "A workflow");
  const props: ComponentProps<"button"> = { type: "button", "aria-haspopup": "dialog", onClick: () => setOpen(true) };
  return (
    <>
      <button {...props} className={look(value !== undefined)}>
        <Label label="Workflow" value={name} />
      </button>
      {open && <Chooser workflows={workflows.data ?? []} value={value} onPick={onChange} onClose={() => setOpen(false)} />}
    </>
  );
}

export function Filters({ tenantId, filters, onChange }: { tenantId: string; filters: RunFilters; onChange: (next: RunFilters) => void }) {
  const set = (change: RunFilters) => onChange({ ...filters, ...change });
  const any = <T extends string>(v: T | "any") => (v === "any" ? undefined : v);
  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-2">
      <WorkflowFilter tenantId={tenantId} value={filters.workflow} onChange={(workflow) => set({ workflow })} />
      <Menu label="Status" choices={STATUS} value={filters.status ?? "any"} onChange={(v) => set({ status: any(v) })} />
      <Menu label="Trigger" choices={TRIGGER} value={filters.trigger ?? "any"} onChange={(v) => set({ trigger: any(v) })} />
      <Menu label="Mode" choices={MODE} value={filters.mode ?? "both"} onChange={(mode) => set({ mode })} />
      <Menu label="Started" choices={STARTED} value={filters.started ?? "24h"} onChange={(started) => set({ started })} />
    </div>
  );
}
