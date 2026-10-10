// SPDX-License-Identifier: Apache-2.0
// The condition builder (4c-2b, the mockups' builder board; the owner's rulings: the builder replaces Fixed for
// conditions, one level of groups, per-comparison guards with "is there" and "is missing" defined). It writes a
// formula (lib/builder.ts) and opens only one it wrote. Comparisons are picked from the data tree; each offers the
// operators its value's type takes. What can't be written yet (a number half typed, a write refused) is held whole,
// with why (ruling 18).
import { useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import {
  isGroup, NO_VALUE, numeric, OP_WORDS, opsFor, read, valueProblem, write, type Condition, type Group, type Literal,
  type Op, type Row,
} from "../../../lib/builder";  // prettier-ignore
import { formula, formulaOf, kindOf } from "../../../lib/config";
import type { ScopeEntry } from "../../../lib/data";
import { useDrawer } from "./context";
import { DataTree } from "./DataTree";
import { PillButton, usePillEntry } from "./Pill";

const EMPTY: Condition = { match: "all", items: [] };

/** The condition a field's value is, when the builder can show it: none yet, or a formula it wrote. */
export function conditionOf(value: unknown): Condition | null {
  if (value === undefined || value === null) return EMPTY;
  if (kindOf(value) === "cel") return read(formulaOf(value));
  return null;
}

/** Why a row's comparison can't be written, or null. */
const rowProblem = (r: Row): string | null =>
  NO_VALUE.has(r.op) || r.value === null ? null : valueProblem(r.value, r.path);

/** What's said under a comparison: what its guards make of missing data (the mockups' notes). */
function noteOf(r: Row): string | null {
  if (r.op === "is_there" || r.op === "is_missing") return null;
  if (r.guards.length > 0) return "If any part of its path is missing, null or another shape, this comparison is false.";
  if (r.nullTest) return "If it's null, this comparison is false.";
  return null;
}

function Match({ label, match, disabled, onChange }: {
  label: string; match: "all" | "any"; disabled: boolean; onChange: (m: "all" | "any") => void;
}) {  // prettier-ignore
  return (
    <div role="group" aria-label={label} className="inline-flex gap-px overflow-hidden rounded-lg border border-line-strong bg-line-strong">
      {(["all", "any"] as const).map((m) => (
        <button
          key={m} type="button" aria-pressed={match === m} disabled={disabled} onClick={() => match !== m && onChange(m)}
          className={`min-h-8 px-3 text-small disabled:bg-disabled-bg disabled:text-muted ${match === m ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          {m === "all" ? "all of these" : "any of these"}
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

function RowView({ row, label, field, disabled, onChange, onRemove }: {
  row: Row; label: string; field: string; disabled: boolean; onChange: (r: Row) => void; onRemove: () => void;
}) {  // prettier-ignore
  const { entry } = usePillEntry(row.path, field);
  const ops = entry ? opsFor(entry.types, entry.format, entry.missing || entry.nullable || row.guards.length > 0) : [row.op];
  const problem = rowProblem(row);
  const note = noteOf(row);
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-1.5 border-t border-line py-2.5">
      <div><PillButton pill={{ ref: row.path }} entry={entry} index={0} onOpen={() => undefined} /></div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={`Comparison, ${label}`} value={row.op} disabled={disabled}
          onChange={(e) => {
            const op = e.target.value as Op;
            const kind = (entry && numeric(entry.types)) || ["more", "less", "at_least", "at_most"].includes(op) ? "number" : "text";
            const value: Literal | null = NO_VALUE.has(op) ? null : { kind, text: row.value?.text ?? "" };
            onChange({ ...row, op, value });
          }}
          className={`${controlClass(false)} w-auto`}
        >
          {(ops.includes(row.op) ? ops : [row.op, ...ops]).map((op) => <option key={op} value={op}>{OP_WORDS[op]}</option>)}
        </select>
        {row.value !== null && (
          <input
            type="text" aria-label={`Value, ${label}`} value={row.value.text} disabled={disabled} spellCheck={false}
            aria-invalid={problem !== null} onChange={(e) => onChange({ ...row, value: { kind: row.value!.kind, text: e.target.value } })}
            className={`${controlClass(problem !== null)} w-auto min-w-0 flex-1`}
          />
        )}
        {!disabled && <Button size="sm" aria-label={`Remove ${label.toLowerCase()}`} onClick={onRemove}>×</Button>}
      </div>
      {problem && <p className="text-small text-danger">{problem}</p>}
      {note && <p className="text-meta text-muted">{note}</p>}
    </div>
  );  // prettier-ignore
}

/** A comparison of an entry picked from the tree, with its first operator. */
function rowFor(entry: ScopeEntry): Row {
  const f = entry.formula!;
  const op = opsFor(entry.types, entry.format, entry.missing || entry.nullable)[0]!;
  const value: Literal | null = NO_VALUE.has(op) ? null : { kind: numeric(entry.types) ? "number" : "text", text: "" };
  return { path: entry.path, op, value, guards: f.guards, nullTest: f.null_test };
}

export function ConditionBuilder({ spec, value, disabled, onChange }: {
  spec: { pointer: string; path: (string | number)[]; label: string; entry: boolean };
  value: unknown; disabled: boolean; onChange: (next: unknown, typed: boolean) => string | null;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const held = drawer.held("condition", spec.pointer);
  const c: Condition = held?.condition ?? conditionOf(value) ?? EMPTY;
  // Where a picked comparison goes: the top, a new group (whose first it is: an empty group writes nothing), a group.
  const [adding, setAdding] = useState<number | "top" | "group" | null>(null);
  const fixed = typeof value === "boolean" ? value : null;

  /** Writes the condition when every comparison can be; else holds it whole, with why. */
  const put = (next: Condition, typed: boolean) => {
    const problem = next.items.flatMap((x) => (isGroup(x) ? x.rows : [x])).map(rowProblem).find((p) => p !== null) ?? null;
    const text = write(next);
    const why = problem ?? onChange(text === undefined ? undefined : formula(text), typed);
    if (why === null) drawer.release("condition", spec.pointer);
    else drawer.hold("condition", spec.pointer, { path: spec.path, label: spec.label, text: text ?? "", condition: next, why, entry: spec.entry });
  };  // prettier-ignore
  const setItem = (i: number, item: Row | Group, typed = false) =>
    put({ ...c, items: c.items.map((x, j) => (j === i ? item : x)) }, typed);
  const removeItem = (i: number) => put({ ...c, items: c.items.filter((_, j) => j !== i) }, false);
  const text = write(c);

  return (
    <div className="flex flex-col gap-2">
      {fixed !== null && c.items.length === 0 && (
        <p className="text-small text-muted">{fixed ? "Always true." : "Always false."} Add a condition to decide on data instead.</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-small">True when</span>
        {/* With fewer than two, all and any write the same: the choice waits for a second. */}
        <Match label={`Match, ${spec.label}`} match={c.match} disabled={disabled || c.items.length < 2} onChange={(match) => put({ ...c, match }, false)} />
      </div>
      <div className="flex flex-col">
        {c.items.map((x, i) =>
          isGroup(x) ? (
            <div key={i} role="group" aria-label={`Group ${i + 1}`} className="flex flex-col gap-1.5 border-t border-line py-2.5 pl-4">
              <div className="flex flex-wrap items-center gap-2">
                <Match label={`Match in group ${i + 1}`} match={x.match} disabled={disabled || x.rows.length < 2} onChange={(match) => setItem(i, { ...x, match })} />
                {!disabled && <Button size="sm" onClick={() => removeItem(i)}>Remove group</Button>}
              </div>
              {x.rows.map((r, k) => (
                <RowView
                  key={k} row={r} label={`Condition ${i + 1}.${k + 1}`} field={spec.pointer} disabled={disabled}
                  onChange={(next) => setItem(i, { ...x, rows: x.rows.map((y, m) => (m === k ? next : y)) }, true)}
                  onRemove={() => setItem(i, { ...x, rows: x.rows.filter((_, m) => m !== k) })}
                />
              ))}
              {!disabled && <div><Button size="sm" onClick={() => setAdding(i)}>＋ Condition</Button></div>}
            </div>
          ) : (
            <RowView
              key={i} row={x} label={`Condition ${i + 1}`} field={spec.pointer} disabled={disabled}
              onChange={(next) => setItem(i, next, true)} onRemove={() => removeItem(i)}
            />
          ),
        )}
      </div>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" aria-haspopup="dialog" onClick={() => setAdding("top")}>＋ Condition</Button>
          <Button size="sm" aria-haspopup="dialog" onClick={() => setAdding("group")}>＋ Group</Button>
        </div>
      )}
      {adding !== null && (
        <DataTree
          field={spec.pointer} purpose="condition" onClose={() => setAdding(null)}
          onPick={(entry) => {
            const row = rowFor(entry);
            const at = adding;
            setAdding(null);
            if (at === "top") put({ ...c, items: [...c.items, row] }, false);
            else if (at === "group") put({ ...c, items: [...c.items, { match: "any", rows: [row] }] }, false);
            else {
              const g = c.items[at];
              if (g && isGroup(g)) setItem(at, { ...g, rows: [...g.rows, row] });
            }
          }}
        />
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small text-muted">
        <dt className="font-semibold text-ink">is there</dt>
        <dd>Present and not null, with every part of the path above it present too. Empty text, 0 and false are there.</dd>
        <dt className="font-semibold text-ink">is missing</dt>
        <dd>The opposite: it, or a part of the path above it, is absent or null.</dd>
        <dt className="font-semibold text-ink">other tests</dt>
        <dd>Each guards its own data and is false when that data is missing, so a missing value never decides a group for the others.</dd>
      </dl>
      {text !== undefined && (
        <details>
          <summary className="cursor-pointer text-small">The formula it writes</summary>
          <pre className="mt-1 overflow-x-auto rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-meta">{text}</pre>
        </details>
      )}
    </div>
  );  // prettier-ignore
}
