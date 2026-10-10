// SPDX-License-Identifier: Apache-2.0
// Text with data pills (4c-2b, the 4c-2 mockups' first board): a text field's fixed mode, one editor for its text and
// the references between it (the owner's ruling: one text and pill editor). Its texts are inputs, each pill a button
// between them, in one box: the text is typed as any text field's is, and a pill is a whole that's moved past, opened
// or removed, never half edited. A pill says what it reads, and is dashed when its value may be missing (ruling 115).
import { useEffect, useRef, type KeyboardEvent } from "react";
import { DataTree } from "./DataTree";
import { PillButton, usePillEntry } from "./Pill";
import { PillDetails } from "./PillDetails";
import {
  insertPill, pillText, removePill, replacePill, segmentsOf, segmentsText, valueOf, withDefault, withText, type Caret, type Pill,
  type Segments,
} from "../../../lib/pills";  // prettier-ignore
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

function Pills({ pill, field, index, onKeyDown, onOpen, buttonRef }: {
  pill: Pill; field: string; index: number; onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void; onOpen: () => void;
  buttonRef: (el: HTMLButtonElement | null) => void;
}) {  // prettier-ignore
  const { entry } = usePillEntry(pill.ref, field);
  return <PillButton pill={pill} entry={entry} index={index} onKeyDown={onKeyDown} onOpen={onOpen} buttonRef={buttonRef} />;
}

/** Whether a "/" typed at this place asks for data: at a text's start or after a space, so a URL's or a path's own
 * slashes stay text. */
export const asksForData = (text: string, offset: number): boolean => offset === 0 || /\s/.test(text[offset - 1] ?? "");

/** What's open under the editor: the tree, to insert at a caret (or to replace a pill), or a pill's details. */
export type Opened = { kind: "tree"; at: Caret; slash: boolean; replace?: number } | { kind: "details"; index: number };

export interface PillsPanel {
  opened: Opened | null;
  open: (opened: Opened | null) => void;
  /** Where the caret was last in this editor: where "+ Data" inserts. */
  caret: { current: Caret | null };
  /** Focus to give once the next render is drawn: a text at an offset, or a pill. */
  focus: { current: { segment: number; offset: number } | { pill: number } | null };
}

export function TextPills({ spec, value, literal, id, describedBy, invalid, disabled, onChange, panel }: ControlProps & { panel: PillsPanel }) {
  const drawer = useDrawer();
  const held = drawer.held("template", spec.pointer);
  const segments: Segments = held?.segments ?? segmentsOf(value) ?? { texts: [""], pills: [] };
  const literalOk = spec.kinds === null || spec.kinds.includes("literal");
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const pills = useRef<(HTMLButtonElement | null)[]>([]);
  const asLiteral = held?.literal ?? literal;

  useEffect(() => {
    const want = panel.focus.current;
    if (!want) return;
    panel.focus.current = null;
    if ("pill" in want) pills.current[want.pill]?.focus();
    else {
      const input = inputs.current[want.segment];
      input?.focus();
      input?.setSelectionRange(want.offset, want.offset);
    }
  });

  /** Writes text and pills as one change; refused, it's held with why, whole (ruling 18). */
  const write = (next: Segments, typed: boolean) => {
    const why = onChange(valueOf(next, asLiteral, literalOk), typed);
    if (why === null) drawer.release("template", spec.pointer);
    else drawer.hold("template", spec.pointer, { path: spec.path, label: spec.label, text: segmentsText(next), segments: next, why, literal: asLiteral, literalOk, entry: spec.entry });
  };  // prettier-ignore

  const caretOf = (segment: number, input: HTMLInputElement): Caret => ({ segment, offset: input.selectionStart ?? input.value.length });

  const onTextKey = (segment: number) => (e: KeyboardEvent<HTMLInputElement>) => {
    const input = e.currentTarget;
    const at = input.selectionStart ?? 0;
    const collapsed = at === (input.selectionEnd ?? at);
    if (e.key === "/" && collapsed && asksForData(input.value, at) && !disabled) {
      // The "/" is typed as text: the tree opens over it, and a pick replaces it (Escape keeps it, as typed).
      panel.caret.current = { segment, offset: at + 1 };
      queueMicrotask(() => panel.open({ kind: "tree", at: { segment, offset: at + 1 }, slash: true }));
    } else if (e.key === "ArrowLeft" && collapsed && at === 0 && segment > 0) {
      e.preventDefault();
      pills.current[segment - 1]?.focus();
    } else if (e.key === "ArrowRight" && collapsed && at === input.value.length && segment < segments.pills.length) {
      e.preventDefault();
      pills.current[segment]?.focus();
    } else if (e.key === "Backspace" && collapsed && at === 0 && segment > 0) {
      e.preventDefault(); // the pill before is focused first: a second Backspace removes it
      pills.current[segment - 1]?.focus();
    }
  };

  const onPillKey = (index: number) => (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      panel.focus.current = { segment: index, offset: segments.texts[index]!.length };
      inputs.current[index]?.focus();
      inputs.current[index]?.setSelectionRange(segments.texts[index]!.length, segments.texts[index]!.length);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      inputs.current[index + 1]?.focus();
      inputs.current[index + 1]?.setSelectionRange(0, 0);
    } else if ((e.key === "Backspace" || e.key === "Delete") && !disabled) {
      e.preventDefault();
      const { segments: next, caret } = removePill(segments, index);
      panel.focus.current = caret;
      write(next, false);
    } else if (e.key === "Enter") {
      e.preventDefault();
      panel.open({ kind: "details", index });
    }
  };

  const labelled = (segment: number) => (segment === 0 ? undefined : `${spec.label}, text after ${pillText(segments.pills[segment - 1]!.ref)}`);

  const opened = panel.opened;
  const box = (
    <div
      className={`flex min-h-11 w-full flex-wrap items-center gap-x-1 gap-y-1.5 rounded-lg border bg-surface px-3 py-2 text-body-lg ${
        invalid ? "border-danger" : "border-line-control"} focus-within:outline focus-within:outline-2 focus-within:outline-focus`}
    >
      {segments.texts.map((text, segment) => (
        <span key={`t${segment}`} className="contents">
          <input
            ref={(el) => void (inputs.current[segment] = el)}
            id={segment === 0 ? id : undefined}
            type="text" value={text} disabled={disabled} spellCheck={false}
            aria-label={labelled(segment)} aria-describedby={segment === 0 ? describedBy : undefined}
            aria-invalid={invalid} aria-required={segment === 0 ? spec.required && !spec.entry : undefined}
            size={Math.max(1, text.length)}
            onKeyDown={onTextKey(segment)}
            onSelect={(e) => void (panel.caret.current = caretOf(segment, e.currentTarget))}
            onChange={(e) => {
              panel.caret.current = caretOf(segment, e.currentTarget);
              write(withText(segments, segment, e.target.value), true);
            }}
            // 24 px at least, empty too: a target a pointer can take (WCAG 2.5.8; the gate found an empty one at 1 ch)
            className={`min-h-[24px] min-w-[24px] max-w-full bg-transparent outline-none [field-sizing:content] ${segments.pills.length === 0 ? "flex-1" : ""}`}
          />
          {segments.pills[segment] && (
            <Pills
              pill={segments.pills[segment]} field={spec.pointer} index={segment} onKeyDown={onPillKey(segment)}
              onOpen={() => panel.open({ kind: "details", index: segment })} buttonRef={(el) => void (pills.current[segment] = el)}
            />
          )}
        </span>
      ))}
    </div>
  );
  const after = (focus: { segment: number; offset: number } | { pill: number }) => {
    panel.focus.current = focus;
    panel.open(null);
  };
  return (
    <div className="flex flex-col gap-2">
      {box}
      {opened?.kind === "tree" && (
        <DataTree
          field={spec.pointer} purpose="text"
          onPick={(entry) => {
            if (opened.replace !== undefined) {
              write(replacePill(segments, opened.replace, entry.path), false);
              after({ pill: opened.replace });
            } else {
              const { next, focus } = withPill(segments, opened.at, entry.path, opened.slash);
              write(next, false);
              after(focus);
            }
          }}
          onClose={() => after(opened.replace !== undefined ? { pill: opened.replace } : opened.at)}
        />
      )}
      {opened?.kind === "details" && segments.pills[opened.index] && (
        <PillDetails
          field={spec.pointer} pill={segments.pills[opened.index]!} defaults
          onDefault={(d) => write(withDefault(segments, opened.index, d), true)}
          onReplace={() => panel.open({ kind: "tree", at: { segment: opened.index + 1, offset: 0 }, slash: false, replace: opened.index })}
          onRemove={() => {
            const { segments: next, caret } = removePill(segments, opened.index);
            write(next, false);
            after(caret);
          }}
          onClose={() => after({ pill: opened.index })}
        />
      )}
    </div>
  );  // prettier-ignore
}

/** Text and pills with a pill put at the caret, and where focus goes then: just after it. */
export function withPill(segments: Segments, where: Caret, ref: string, slash: boolean): { next: Segments; focus: Caret } {
  // A caret past the end (none yet: "+ Data" before any typing) is the end of the last text.
  const last = segments.texts.length - 1;
  const at = where.segment > last ? { segment: last, offset: segments.texts[last]!.length } : where;
  // A "/" typed to ask for it is replaced by the pill (asksForData).
  const text = segments.texts[at.segment] ?? "";
  const dropped = slash && text[at.offset - 1] === "/" ? withText(segments, at.segment, text.slice(0, at.offset - 1) + text.slice(at.offset)) : segments;
  const offset = slash && text[at.offset - 1] === "/" ? at.offset - 1 : at.offset;
  return { next: insertPill(dropped, { segment: at.segment, offset }, { ref }), focus: { segment: at.segment + 1, offset: 0 } };
}
