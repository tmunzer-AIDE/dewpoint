// SPDX-License-Identifier: Apache-2.0
// An update's changes and a create's settings (4f-2, the Mist step design §5.3–§5.9): one fieldset on Setup, the body
// drawn as a row per setting it sets or clears, by title, never all its settings at once. The body is the drawer's own
// field: List or Formula, what's typed, held or computed behaves as everywhere, and a body it can't draw as a list shows
// today's control (ledger 102). Each row's setting is the drawer's own field too, its name beside its title; Set, Clear
// and Keep change `body` and `clear` together, one step of Undo. What it remembers until the drawer closes (a value set
// before it was cleared, a setting added with nothing given) lives above the tabs, which unmount what they hide.
import { useRef, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import {
  WORDS, bodyObject, changedCount, clearIn, clearNames, keepIn, rowsOf, setIn, summaryOf, type Memory, type Row,
} from "../../../lib/changes";  // prettier-ignore
import { fixedOf, valueAt } from "../../../lib/config";
import { isObject, offeredOf, pointerOf, propertiesOf, type Changes as Parts, type FieldSpec } from "../../../lib/schemaForm";
import { settingsOf, type Setting } from "../../../lib/settingsIndex";
import { problemsAt, useDrawer } from "./context";
import { FindSetting } from "./FindSetting";
import { FieldView } from "./FieldView";
import type { ControlProps } from "./scalars";

const NARROW = "max-sm:min-h-[44px]"; // 44 px targets at 320 (§5.11), in pixels: a rem is 14 px here

/** Focus, once drawn, the control at `pointer`, else its nearest drawn holder's first: a setting just added. */
function focusAt(pointer: string) {
  requestAnimationFrame(() => {
    for (let at = pointer; at !== ""; at = at.slice(0, at.lastIndexOf("/"))) {
      const holder = [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === at);
      if (!holder) continue;
      const label = holder.querySelector<HTMLLabelElement>("label[for]");
      const control = (label && document.getElementById(label.htmlFor)) ?? holder.querySelector<HTMLElement>("input, select, textarea, button");
      control?.focus();
      return;
    }
  });
}

/** How they're sent: merge or replace, a radio pair, merge when unset (`mode`'s default); stacked at 320 px. */
function ModeControl({ value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const current = value === "replace" ? "replace" : "merge";
  return (
    <div
      id={id} role="radiogroup" aria-label="How the changes are sent" aria-describedby={describedBy} aria-invalid={invalid} tabIndex={-1}
      className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap"
    >
      {(["merge", "replace"] as const).map((choice) => (
        <label key={choice} className={`flex min-h-[24px] items-center gap-2 rounded-lg border border-line-control px-3 text-body ${NARROW}`}>
          <input type="radio" name={id} value={choice} checked={current === choice} disabled={disabled} onChange={() => onChange(choice, false)} />
          {choice === "merge" ? WORDS.merge : WORDS.replace}
        </label>
      ))}
    </div>
  );  // prettier-ignore
}

/** A row's Set | Clear and Keep (an update's), or Remove (a create's, unless the setting is required). */
function RowActions({ row, update, onSet, onClear, onKeep }: {
  row: Row; update: boolean; onSet: () => void; onClear: () => void; onKeep: () => void;
}) {  // prettier-ignore
  const drawer = useDrawer();
  if (!drawer.editable) return null;
  if (!update) {
    return row.spec.required ? null : (
      <Button size="sm" aria-label={`Remove ${row.spec.label}`} className={NARROW} onClick={onKeep}>Remove</Button>
    );
  }
  const choice = "min-h-[28px] px-2.5 text-small aria-pressed:bg-accent-soft aria-pressed:font-semibold aria-pressed:text-accent-ink " + NARROW;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span role="group" aria-label={`What happens to ${row.spec.label}`} className="inline-flex overflow-hidden rounded-md border border-line-strong">
        <button type="button" aria-pressed={row.state === "set" || row.state === "pending"} className={choice} onClick={onSet}>Set</button>
        <button type="button" aria-pressed={row.state === "clear"} className={`${choice} border-l border-line-strong`} onClick={onClear}>Clear</button>
      </span>
      <Button size="sm" aria-label={`Keep ${row.spec.label} as it is`} className={NARROW} onClick={onKeep}>Keep</Button>
    </span>
  );  // prettier-ignore
}

/** A row that draws no value: cleared, or both set and cleared. */
function SaidRow({ row, actions, said }: { row: Row; actions: ReactNode; said: string }) {
  return (
    <div data-pointer={row.spec.pointer} className="flex min-w-0 flex-col gap-1.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="flex flex-col">
          <span className="text-small font-semibold">{row.spec.label}</span>
          <span className="font-mono text-meta text-muted">{row.name}</span>
        </span>
        {actions}
      </div>
      <p className="text-small">{said}</p>
    </div>
  );
}

export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Memory; onMemory: (next: Memory) => void }) {
  const drawer = useDrawer();
  const config = drawer.node.config ?? {};
  const update = parts.widget === "update";
  const label = update ? "Changes" : "Settings";
  const body = bodyObject(config);
  const names = clearNames(config);
  const offered = offeredOf(parts.body);
  // A `clear` naming what the list doesn't offer is a draft from elsewhere: today's control, unchanged (§5.8).
  const clearDrawn = parts.clear !== null && names !== null && names.every((n) => offered.some((s) => s.name === n));
  const rows = rowsOf(offered, body ?? {}, clearDrawn ? names : [], memory.pending);
  const replace = fixedOf(valueAt(config, ["mode"])) === "replace";
  const nothing = update && body !== null && rows.every((r) => r.state === "pending");
  const settings = settingsOf(parts.body);
  const find = useRef<HTMLInputElement>(null);

  // One write of the whole config: `body` and `clear` together, one step of Undo. What's typed under the row is
  // dropped first by Clear and Keep (what it would write goes with the row), applied first by Set.
  const change = (row: Row, make: (cfg: Record<string, unknown>) => Record<string, unknown>, drop: boolean) => {
    if (drop) drawer.discard(row.spec.pointer);
    return drawer.restructure(row.spec.pointer, { path: [], make: (cfg) => make(isObject(cfg) ? cfg : {}) });
  };
  const remember = (next: Partial<Memory>) => onMemory({ ...memory, ...next });
  const set = (row: Row) => {
    if (row.state === "set") return;
    const value = row.state === "both" ? (body ?? {})[row.name] : memory.cleared[row.name];
    if (change(row, (cfg) => setIn(cfg, row.name, value), false) === null && value === undefined) {
      remember({ pending: [...memory.pending.filter((n) => n !== row.name), row.name] });
    }
  };
  const clear = (row: Row) => {
    if (row.state === "clear") return;
    const value = (body ?? {})[row.name];
    if (change(row, (cfg) => clearIn(cfg, row.name), true) === null) {
      remember({ cleared: value === undefined ? memory.cleared : { ...memory.cleared, [row.name]: value }, pending: memory.pending.filter((n) => n !== row.name) });
    }
  };
  const keep = (row: Row) => {
    if (change(row, (cfg) => keepIn(cfg, row.name), true) === null) {
      const cleared = Object.fromEntries(Object.entries(memory.cleared).filter(([n]) => n !== row.name));
      remember({ cleared, pending: memory.pending.filter((n) => n !== row.name) });
    }
  };

  // Added from Find: a setting not listed yet is Set, nothing given until a value is (§5.4); focus goes to it.
  const add = (s: Setting) => {
    const top = s.steps[0]!.name;
    if (!rows.some((r) => r.name === top)) remember({ pending: [...memory.pending, top] });
    focusAt(pointerOf([...parts.body.path, ...s.steps.map((step) => step.name)]));
  };

  const rowView = (row: Row) => {
    const actions = <RowActions row={row} update={update} onSet={() => set(row)} onClear={() => clear(row)} onKeep={() => keep(row)} />;
    if (row.state === "clear") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.cleared} />;
    if (row.state === "both") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.both} />;
    const json = row.spec.widget === "json" && !row.spec.holdsSensitive;
    return (
      <FieldView
        key={row.name} spec={row.spec}
        drawn={{
          name: row.name, hideClear: true, actions, startFixed: json, hint: json ? WORDS.json : undefined,
          below: row.state === "pending" && drawer.editable ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
        }}
      />
    );  // prettier-ignore
  };

  const mode = parts.mode && (
    <FieldView
      spec={{ ...parts.mode, label: "How they're sent" }}
      drawn={{ control: ModeControl, hideClear: true, switchLabel: "the way they're sent", hint: replace ? null : WORDS.mergeSays, warn: replace ? WORDS.replaceSays : null }}
    />
  );
  const clearControl = parts.clear && !clearDrawn && <FieldView spec={parts.clear} />;

  const list = () => {
    if (!drawer.editable) {
      const summary = summaryOf(parts.widget, rows, body ?? {}, valueAt(config, ["mode"]), propertiesOf);
      return (
        <>
          <p className="text-small">{summary.head}</p>
          <dl className="grid grid-cols-1 gap-x-3 gap-y-1 text-small sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
            {summary.lines.map((l) => (
              <div key={l.name} className="contents">
                <dt className="text-muted">{l.label}</dt>
                <dd className="m-0">{l.text}</dd>
              </div>
            ))}
          </dl>
        </>
      );
    }
    // The rows hold `clear` too: a Go to or a problem there lands on them.
    const atClear = parts.clear && clearDrawn ? problemsAt(drawer.problems, parts.clear.pointer, null) : [];
    return (
      <>
        {mode}
        <FindSetting ref={find} settings={settings} listed={new Set(rows.map((r) => r.name))} where={label} onAdd={add} />
        <div data-pointer={parts.clear && clearDrawn ? parts.clear.pointer : undefined} className="flex min-w-0 flex-col gap-4">
          {rows.map(rowView)}
          {atClear.map((d, i) => (
            <p key={`${d.code}:${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>{d.message}</p>
          ))}
        </div>
        {clearControl}
        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => find.current?.focus()}>
          ＋ Add a setting
        </button>
        <p className="text-small text-muted">{WORDS.count(parts.widget, changedCount(rows), offered.length)}</p>
      </>
    );
  };

  // A body a formula gives: its cleared settings stay listed, how they're sent with them (§5.8).
  const computed = body === null && (
    <div className="flex min-w-0 flex-col gap-4">
      <p className="text-small text-muted">{update ? WORDS.formulaUpdate : WORDS.formulaCreate}</p>
      {mode}
      {rowsOf(offered, {}, clearDrawn ? names : [], []).map(rowView)}
      {clearControl}
    </div>
  );

  return (
    <FieldView
      spec={{ ...parts.body, label } satisfies FieldSpec}
      drawn={{
        group: true, startFixed: true, fixedName: "List", hideClear: true, hint: null,
        shown: rows.map((r) => r.name), warn: nothing ? WORDS.nothing : null, parts: list, below: computed || undefined,
      }}
    />
  );  // prettier-ignore
}
