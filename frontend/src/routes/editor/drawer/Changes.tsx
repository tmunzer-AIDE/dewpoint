// SPDX-License-Identifier: Apache-2.0
// An update's changes and a create's settings (4f-2, the Mist step design §5.3–§5.9): one fieldset on Setup, the body
// drawn as a row per setting it sets or clears, by title, never all its settings at once. The body is the drawer's own
// field: List or Formula, what's typed, held or computed behaves as everywhere, and a body it can't draw as a list shows
// today's control (ledger 102). Each row's setting is the drawer's own field too, its name beside its title; Set, Clear
// and Keep change `body` and `clear` together, one step of Undo. What it remembers until the drawer closes (a value set
// before it was cleared, a setting added with nothing given) lives above the tabs, which unmount what they hide.
import { useId, useRef, useState, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import {
  WORDS, bodyObject, changedCount, clearIn, clearNames, drawnAt, isComputed, keepIn, kindIn, kindIndex, rowsOf, setIn, summaryOf, type Memory,
  type Row,
} from "../../../lib/changes";  // prettier-ignore
import { fixedOf, valueAt } from "../../../lib/config";
import {
  branchesOf, isObject, kindOf, offeredOf, propertiesOf, unionTitle, type Changes as Parts, type FieldSpec,
} from "../../../lib/schemaForm";  // prettier-ignore
import { settingsOf, type Setting } from "../../../lib/settingsIndex";
import { EmptiedContext, problemsAt, useDrawer } from "./context";
import { FindSetting } from "./FindSetting";
import { PartsContext, drawnNames, focusLater, found, partsOf } from "./GivenParts";
import { FieldView } from "./FieldView";
import type { ControlProps } from "./scalars";

const NARROW = "max-sm:min-h-[44px]"; // 44 px targets at 320 (§5.11), in pixels: a rem is 14 px here


/** How they're sent: merge or replace, a radio pair, merge when unset (`mode`'s default); stacked at 320 px. */
function ModeControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const current = value === "replace" ? "replace" : "merge";
  return (
    <div
      id={id} role="radiogroup" aria-label={spec.label} aria-describedby={describedBy} aria-invalid={invalid} tabIndex={-1}
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
function RowActions({ row, update, canSet, canClear, onSet, onClear, onKeep }: {
  row: Row; update: boolean; canSet: boolean; canClear: boolean; onSet: () => void; onClear: () => void; onKeep: () => void;
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
        {/* Under a body a formula gives, nothing is set; a `clear` it can't read takes nothing more (the final review). */}
        {canSet && <button type="button" aria-pressed={row.state === "set" || row.state === "pending"} className={choice} onClick={onSet}>Set</button>}
        {canClear && <button type="button" aria-pressed={row.state === "clear"} className={`${choice} ${canSet ? "border-l border-line-strong" : ""}`} onClick={onClear}>Clear</button>}
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

/** A change of kind's words, before the config it wrote is drawn. */
const NEXT = Symbol("the next config");

export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Memory; onMemory: (update: (memory: Memory) => Memory) => void }) {
  const drawer = useDrawer();
  const config = drawer.node.config ?? {};
  const update = parts.widget === "update";
  const label = update ? "Changes" : "Settings";
  const body = bodyObject(config);
  const names = clearNames(config);
  // A union of kinds (a device's): its kind first, the settings offered the chosen kind's (§5.7); an update's read
  // from its value, the one chosen here, or the settings listed; a create's only from its value, written when picked.
  const branches = branchesOf(parts.body);
  const kind = kindOf(branches);
  const kindNames = kind ? branches.map((b) => offeredOf(b, kind.name).map((p) => p.name)) : [];
  const listed = [...Object.keys(body ?? {}), ...(names ?? [])].filter((n) => n !== kind?.name);
  const index = kind ? kindIndex(parts.widget, body ?? {}, listed, kind, kindNames, memory.kind) : null;
  const scope = kind ? (index === null ? null : branches[index]!) : parts.body;
  const offered = scope ? offeredOf(scope, kind?.name ?? null) : [];
  const required = update || scope === null || !Array.isArray(scope.schema.required) ? [] :
    (scope.schema.required as unknown[]).filter((n): n is string => typeof n === "string" && offered.some((o) => o.name === n));  // prettier-ignore
  const kindId = useId();
  // What a change of kind kept and dropped, of the config it wrote (`of`: the next one drawn); an Undo or any later
  // edit forgets it (F5).
  const [said, setSaid] = useState<{ words: string; of: unknown } | null>(null);
  const held = drawer.node.config;
  if (said !== null && said.of !== held) setSaid(said.of === NEXT ? { ...said, of: held } : null);
  // A `clear` naming what the list doesn't offer is a draft from elsewhere: today's control, unchanged (§5.8).
  const clearDrawn = parts.clear !== null && names !== null && names.every((n) => offered.some((s) => s.name === n));
  const rows = rowsOf(offered, body ?? {}, clearDrawn ? names : [], memory.pending, required);
  const replace = fixedOf(valueAt(config, ["mode"])) === "replace";
  // How they're sent a formula gives: neither's words under the settings, the mode's field says it (F5).
  const modeComputed = isComputed(valueAt(config, ["mode"]));
  // Nothing sent: the body empty and `clear` too, a setting the list doesn't draw counted (the final review).
  const nothing = update && body !== null && Object.keys(body).length === 0 && names !== null && names.length === 0;
  const settings = scope ? settingsOf(scope, kind?.name ?? null) : [];
  const find = useRef<HTMLInputElement>(null);

  // One write of the whole config: `body` and `clear` together, one step of Undo. What's typed under the row is
  // dropped first by Clear and Keep (what it would write goes with the row), applied first by Set.
  const change = (row: Row, make: (cfg: Record<string, unknown>) => Record<string, unknown>, drop: boolean) => {
    if (drop) drawer.discard(row.spec.pointer);
    return drawer.restructure(row.spec.pointer, { path: [], make: (cfg) => make(isObject(cfg) ? cfg : {}) });
  };
  // Merged into the memory as it is then: two in one handler both land; one made from it builds on those before.
  const remember = (next: Partial<Memory> | ((now: Memory) => Partial<Memory>)) =>
    onMemory((now) => ({ ...now, ...(typeof next === "function" ? next(now) : next) }));
  const set = (row: Row) => {
    if (row.state === "set") return;
    const value = row.state === "both" ? (body ?? {})[row.name] : memory.cleared[row.name];
    // Added, nothing given and nothing to bring back: nothing to write, its control focused (F5).
    if (row.state === "pending" && value === undefined) {
      focusLater(row.spec.pointer);
      return;
    }
    if (change(row, (cfg) => setIn(cfg, row.name, value), false) !== null) return;
    if (value === undefined) remember({ pending: [...memory.pending.filter((n) => n !== row.name), row.name] });
    focusLater(row.spec.pointer);
  };
  const clear = (row: Row) => {
    if (row.state === "clear") return;
    const value = (body ?? {})[row.name];
    if (change(row, (cfg) => clearIn(cfg, row.name), true) === null) {
      remember({ cleared: value === undefined ? memory.cleared : { ...memory.cleared, [row.name]: value }, pending: memory.pending.filter((n) => n !== row.name) });
      focusLater(row.spec.pointer, "pressed");
    }
  };
  const keep = (row: Row) => {
    if (change(row, (cfg) => keepIn(cfg, row.name), true) === null) {
      const cleared = Object.fromEntries(Object.entries(memory.cleared).filter(([n]) => n !== row.name));
      remember({ cleared, pending: memory.pending.filter((n) => n !== row.name) });
      focusLater(parts.body.pointer, "add");
    }
  };

  // Added from Find (§5.4): a setting not listed yet is Set, nothing given until a value is; a nested one opens each
  // object on its way, a map's new entry asks its key first, a list gets a new item (written: its place is the
  // person's); focus goes to it.
  const add = (s: Setting) => {
    const top = s.steps[0]!.name;
    const done = found(drawer, config, memory, parts.body, s);
    if (done === null) return;
    remember(rows.some((r) => r.name === top) ? done.next : { ...done.next, pending: [...memory.pending, top] });
    if (done.focus !== null) focusLater(done.focus);
  };
  // Another kind: the changes it has too are kept, the others dropped, said; its value written where it's held.
  const toKind = (to: number) => {
    if (!kind || to === index) return;
    const target = branches[to]!;
    const names = kindNames[to]!;
    const out: { done?: ReturnType<typeof kindIn> } = {};
    const write = !update || (body ?? {})[kind.name] !== undefined;
    const why = drawer.restructure(parts.body.pointer, { path: [], make: (cfg) => (out.done = kindIn(isObject(cfg) ? cfg : {}, kind, to, names, write, kindNames.flat())).config });
    if (why !== null || out.done === undefined) return;
    const { kept, dropped } = out.done;
    const titled = (n: string) => branches.flatMap((b) => propertiesOf(b)).find((p) => p.name === n)?.label ?? n;
    remember({ kind: kind.values[to]!, pending: memory.pending.filter((n) => names.includes(n)) });
    setSaid(kept.length + dropped.length > 0 ? { words: WORDS.kindChanged(target.label, kept.map(titled), dropped.map(titled)), of: NEXT } : null);
  };
  const kindLabel = `Kind of ${(unionTitle(parts.body) ?? "it").replace(/^./, (c) => c.toLowerCase())}`;
  const kindControl = kind && (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span id={kindId} className="text-small font-semibold">{kindLabel}</span>
      <div role="radiogroup" aria-labelledby={kindId} className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
        {branches.map((b, i) => (
          <label key={b.label} className={`flex min-h-[24px] items-center gap-2 rounded-lg border border-line-control px-3 text-body ${NARROW}`}>
            <input type="radio" name={kindId} checked={index === i} disabled={!drawer.editable} onChange={() => toKind(i)} />
            {b.label}
          </label>
        ))}
      </div>
      <p className="text-small text-muted">{index === null ? WORDS.chooseKind : `Its settings are the ${branches[index]!.label}'s.`}</p>
      {/* There from the start, so what's said is announced (F5). */}
      <p role="status" className={said === null ? "sr-only" : "text-small"}>{said?.words}</p>
    </div>
  );  // prettier-ignore

  // A setting emptied by a Remove inside it keeps its row, nothing given yet.
  const top = (name: string) => remember((now) => (now.pending.includes(name) ? {} : { pending: [...now.pending, name] }));

  // A hit's own place drawn: its setting's row, then each part under it (F5, the owner's ruling).
  const drawnHere = (s: Setting) => {
    const row = rows.find((r) => r.name === s.steps[0]!.name);
    return row !== undefined && drawnAt(s.steps.slice(1), (body ?? {})[row.name], row.spec.path, memory.shown);
  };

  const rowView = (row: Row) => {
    const actions = (
      <RowActions
        row={row} update={update} canSet={body !== null} canClear={names !== null}
        onSet={() => set(row)} onClear={() => clear(row)} onKeep={() => keep(row)}
      />
    );  // prettier-ignore
    if (row.state === "clear") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.cleared} />;
    if (row.state === "both") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.both} />;
    const json = row.spec.widget === "json" && !row.spec.holdsSensitive;
    const drawnParts = partsOf(row.spec);
    const pendingSaid = row.state === "pending" && drawer.editable && !required.includes(row.name);
    const said = json ? WORDS.json : drawnParts && update && !modeComputed && row.spec.base !== "list" ? (replace ? WORDS.partsReplace : WORDS.partsMerge) : undefined;
    // The setting's own description first, then how it's sent: one paragraph (F5).
    const hint = said === undefined ? undefined : [row.spec.hint, said].filter(Boolean).join(" ");
    return (
      <EmptiedContext.Provider key={row.name} value={() => top(row.name)}>
      <FieldView
        spec={row.spec}
        drawn={{
          name: row.name, hideClear: true, actions, startFixed: json, hint, parts: drawnParts,
          shown: drawnNames(row.spec, (body ?? {})[row.name], memory),
          below: pendingSaid ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
        }}
      />
      </EmptiedContext.Provider>
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
      // The kind said first; `clear`'s names the list can't draw each said as written, the others as rows (F5).
      const offers = (n: string) => offered.some((s) => s.name === n);
      const cleared = parts.clear !== null ? (names ?? []) : [];
      const summed = clearDrawn ? rows : rowsOf(offered, body ?? {}, cleared.filter(offers), memory.pending, required);
      const summary = summaryOf(parts.widget, summed, body ?? {}, valueAt(config, ["mode"]), propertiesOf, {
        kind: kind && index !== null ? { name: kind.name, label: kindLabel, text: branches[index]!.label } : null,
        cleared: clearDrawn ? [] : cleared.filter((n) => !offers(n)),
      });
      return (
        <>
          <p className="text-small">{summary.head}</p>
          <dl className="grid grid-cols-1 gap-x-3 gap-y-1 text-small sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
            {summary.lines.map((l, i) => (
              <div key={i} className="contents">
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
    // A create's kind not chosen yet: nothing else to give. The kind keeps its place at the first pick (F5).
    if (scope === null) return <>{kindControl}</>;
    return (
      <>
        {kindControl}
        {mode}
        <FindSetting ref={find} settings={settings} drawn={drawnHere} where={label} onAdd={add} />
        <div data-pointer={parts.clear && clearDrawn ? parts.clear.pointer : undefined} className="flex min-w-0 flex-col gap-4">
          {rows.map(rowView)}
          {atClear.map((d, i) => (
            <p key={`${d.code}:${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>{d.message}</p>
          ))}
        </div>
        {clearControl}
        <button type="button" data-add-for={parts.body.pointer} className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => find.current?.focus()}>
          ＋ Add a setting
        </button>
        <p className="text-small text-muted">{WORDS.count(parts.widget, changedCount(rows), offered.length)}</p>
      </>
    );
  };

  // One field, today's control (F5): a body the list can't read (held as a literal, an envelope it can't read), or a
  // union whose kinds it can't tell apart. A body a formula, a reference or a template gives is the list's other side.
  const oneField = (body === null && !isComputed(config.body)) || (branches.length > 1 && kind === null);
  // Beside a body the list doesn't draw: its cleared settings stay listed, how they're sent with them, once; a formula's
  // words only when it's computed (§5.8, F5).
  const beside = (body === null || oneField) && (
    <div className="flex min-w-0 flex-col gap-4">
      {isComputed(config.body) && <p className="text-small text-muted">{update ? WORDS.formulaUpdate : WORDS.formulaCreate}</p>}
      {mode}
      {rowsOf(offered, {}, clearDrawn ? names : [], []).map(rowView)}
      {clearControl}
    </div>
  );

  return (
    <PartsContext.Provider value={{ memory, remember, where: label }}>
    <FieldView
      spec={{ ...parts.body, label } satisfies FieldSpec}
      drawn={{
        group: !oneField, startFixed: true, fixedName: oneField ? undefined : "List", hideClear: true, hint: null,
        shown: rows.map((r) => r.name), warn: nothing ? WORDS.nothing : null, parts: oneField ? undefined : list, below: beside || undefined,
      }}
    />
    </PartsContext.Provider>
  );  // prettier-ignore
}
