// SPDX-License-Identifier: Apache-2.0
// Text with data pills (4c-2b, the 4c-2 mockups' first board): a text field's fixed mode, one editor for its text and
// the references between it (the owner's ruling: one text and pill editor). Its texts are inputs, each pill a button
// between them, in one box: the text is typed as any text field's is, and a pill is a whole that's moved past, opened
// or removed, never half edited. A pill says what it reads, and is dashed when its value may be missing (ruling 115).
// Its text is laid out in lines, an input for each piece of text between pills and newlines; a field that takes several
// lines (the message's text, 4f-1) starts one with Enter and joins one to the line above with Backspace at its start.
import { useEffect, useRef, type KeyboardEvent } from "react";
import { DataTree } from "./DataTree";
import { PillButton, usePillEntry } from "./Pill";
import { PillDetails } from "./PillDetails";
import {
  insertPill, linesOf, pillText, removePill, replacePill, segmentsOf, segmentsText, valueOf, withDefault, withText, type Caret,
  type Pill, type Segments,
} from "../../../lib/pills";  // prettier-ignore
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

function Pills({ pill, field, index, onKeyDown, onOpen, buttonRef }: {
  pill: Pill; field: string; index: number; onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void; onOpen: () => void;
  buttonRef: (el: HTMLButtonElement | null) => void;
}) {  // prettier-ignore
  const { shown } = usePillEntry(pill.ref, field);
  return <PillButton pill={pill} entry={shown} index={index} onKeyDown={onKeyDown} onOpen={onOpen} buttonRef={buttonRef} />;
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

/** Keys that move the caret, pressed without a modifier: a modified one is the browser's (a selection, a shortcut). */
const plain = (e: KeyboardEvent) => !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey;

export function TextPills({ spec, value, literal, id, describedBy, invalid, disabled, onChange, panel, lines = false }: ControlProps & {
  panel: PillsPanel; lines?: boolean;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const held = drawer.held("template", spec.pointer);
  const segments: Segments = held?.segments ?? segmentsOf(value) ?? { texts: [""], pills: [] };
  const literalOk = spec.kinds === null || spec.kinds.includes("literal");
  const rows = linesOf(segments);
  const pieces = rows.flat().map((item) => item.piece);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const pills = useRef<(HTMLButtonElement | null)[]>([]);
  const asLiteral = held?.literal ?? literal;

  /** Focus at a place of a segment's text: the input holding it. A place past the end ("＋ Data" pressed before the
   * text was ever focused asks for it) is the end of the last text (the final review). */
  const focusAt = (segment: number, offset: number) => {
    let index = pieces.findIndex((p) => p.segment === segment && offset >= p.start && offset <= p.start + p.text.length);
    if (index < 0) index = Math.max(0, pieces.findLastIndex((p) => p.segment === Math.min(segment, segments.texts.length - 1)));
    const piece = pieces[index]!;
    const at = Math.max(0, Math.min(offset - piece.start, piece.text.length));
    inputs.current[index]?.focus();
    inputs.current[index]?.setSelectionRange(at, at);
  };

  useEffect(() => {
    const want = panel.focus.current;
    if (!want) return;
    panel.focus.current = null;
    if ("pill" in want) pills.current[want.pill]?.focus();
    else focusAt(want.segment, want.offset);
  });

  /** Writes text and pills as one change; refused, it's held with why, whole (ruling 18). */
  const write = (next: Segments, typed: boolean) => {
    const why = onChange(valueOf(next, asLiteral, literalOk), typed);
    if (why === null) drawer.release("template", spec.pointer);
    else drawer.hold("template", spec.pointer, { path: spec.path, label: spec.label, text: segmentsText(next), segments: next, why, literal: asLiteral, literalOk, entry: spec.entry });
  };  // prettier-ignore

  const caretOf = (index: number, input: HTMLInputElement): Caret => ({
    segment: pieces[index]!.segment, offset: pieces[index]!.start + (input.selectionStart ?? input.value.length),
  });  // prettier-ignore
  const rowOf = (index: number) => rows.findIndex((row) => row.some((item) => item.piece === pieces[index]));

  const onTextKey = (index: number) => (e: KeyboardEvent<HTMLInputElement>) => {
    const { segment, start } = pieces[index]!;
    const text = segments.texts[segment]!;
    const input = e.currentTarget;
    const at = input.selectionStart ?? 0;
    const end = input.selectionEnd ?? at;
    const collapsed = at === end;
    const offset = start + at; // in the segment's text, its newlines counted
    if (e.key === "/" && collapsed && asksForData(input.value, at) && !disabled) {
      // The "/" is typed as text: the tree opens over it, and a pick replaces it (Escape keeps it, as typed). It opens in
      // the next task, once the browser has typed the "/": opened in a microtask, React draws it with the keydown, and
      // the tree's search takes focus, and the "/", first (seen in a browser, #85).
      panel.caret.current = { segment, offset: offset + 1 };
      setTimeout(() => panel.open({ kind: "tree", at: { segment, offset: offset + 1 }, slash: true }), 0);
    } else if (lines && e.key === "Enter" && !e.altKey && !e.metaKey && !e.ctrlKey && !disabled) {
      e.preventDefault(); // a new line at the caret, what's selected replaced
      panel.focus.current = { segment, offset: offset + 1 };
      write(withText(segments, segment, `${text.slice(0, offset)}\n${text.slice(start + end)}`), true);
    } else if (e.key === "Backspace" && collapsed && at === 0 && start > 0 && !disabled) {
      e.preventDefault(); // at a line's start: joined to the line above
      panel.focus.current = { segment, offset: offset - 1 };
      write(withText(segments, segment, text.slice(0, offset - 1) + text.slice(offset)), true);
    } else if (e.key === "ArrowLeft" && collapsed && at === 0 && start > 0 && plain(e)) {
      e.preventDefault();
      focusAt(segment, offset - 1); // the end of the line above
    } else if (e.key === "ArrowRight" && collapsed && at === input.value.length && offset < text.length && plain(e)) {
      e.preventDefault();
      focusAt(segment, offset + 1); // the start of the line below
    } else if (e.key === "ArrowLeft" && collapsed && at === 0 && segment > 0) {
      e.preventDefault();
      pills.current[segment - 1]?.focus();
    } else if (e.key === "ArrowRight" && collapsed && at === input.value.length && segment < segments.pills.length) {
      e.preventDefault();
      pills.current[segment]?.focus();
    } else if (e.key === "Backspace" && collapsed && at === 0 && segment > 0) {
      e.preventDefault(); // the pill before is focused first: a second Backspace removes it
      pills.current[segment - 1]?.focus();
    } else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && plain(e)) {
      // To the line above or below, its first text, as far in as the caret was in this one.
      const row = rows[rowOf(index) + (e.key === "ArrowUp" ? -1 : 1)];
      if (!row) return;
      e.preventDefault();
      const first = row[0]!.piece;
      focusAt(first.segment, first.start + Math.min(at, first.text.length));
    } else if ((e.key === "Home" || e.key === "End") && plain(e)) {
      // To the line's start or end, past its pills: an input's own Home stops at the pill before it.
      const row = rows[rowOf(index)]!;
      const piece = e.key === "Home" ? row[0]!.piece : row.at(-1)!.piece;
      e.preventDefault();
      focusAt(piece.segment, piece.start + (e.key === "Home" ? 0 : piece.text.length));
    }
  };

  const onPillKey = (index: number) => (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault(); // focused now, as → does: a focus request left for later would move the caret back as one types
      focusAt(index, segments.texts[index]!.length);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      focusAt(index + 1, 0);
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

  /** The first input is the field's, its label naming it; one after a pill says the pill, one on a later line its line. */
  const labelled = (index: number, row: number) => {
    const { segment, start } = pieces[index]!;
    if (segment === 0 && start === 0) return undefined;
    return start === 0 ? `${spec.label}, text after ${pillText(segments.pills[segment - 1]!.ref)}` : `${spec.label}, line ${row + 1}`;
  };

  const opened = panel.opened;
  let index = -1; // each piece's input, in the order they're drawn
  const box = (
    <div
      className={`flex min-h-11 w-full flex-col justify-center gap-y-1.5 rounded-lg border bg-surface px-3 py-2 text-body-lg ${
        invalid ? "border-danger" : "border-line-control"} focus-within:outline focus-within:outline-2 focus-within:outline-focus`}
    >
      {rows.map((row, r) => (
        <div key={r} className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-1.5">
          {row.map(({ piece, pill }, k) => {
            const i = ++index;
            return (
              <span key={i} className="contents">
                <input
                  ref={(el) => void (inputs.current[i] = el)}
                  id={i === 0 ? id : undefined}
                  type="text" value={piece.text} disabled={disabled} spellCheck={false}
                  aria-label={labelled(i, r)} aria-describedby={i === 0 ? describedBy : undefined}
                  aria-invalid={invalid} aria-required={i === 0 ? spec.required && !spec.entry : undefined}
                  size={Math.max(1, piece.text.length)}
                  onKeyDown={onTextKey(i)}
                  onSelect={(e) => void (panel.caret.current = caretOf(i, e.currentTarget))}
                  onChange={(e) => {
                    panel.caret.current = caretOf(i, e.currentTarget);
                    const text = segments.texts[piece.segment]!;
                    write(withText(segments, piece.segment, text.slice(0, piece.start) + e.target.value + text.slice(piece.start + piece.text.length)), true);
                  }}
                  // 24 px at least, empty too: a target a pointer can take (WCAG 2.5.8; the gate found an empty one at 1 ch).
                  // A line's last text takes the rest of the line, where several lines are typed.
                  className={`min-h-[24px] min-w-[24px] max-w-full bg-transparent outline-none [field-sizing:content] ${
                    (lines ? k === row.length - 1 : segments.pills.length === 0) ? "flex-1" : ""}`}
                />
                {pill !== null && (
                  <Pills
                    pill={segments.pills[pill]!} field={spec.pointer} index={pill} onKeyDown={onPillKey(pill)}
                    onOpen={() => panel.open({ kind: "details", index: pill })} buttonRef={(el) => void (pills.current[pill] = el)}
                  />
                )}
              </span>
            );
          })}
        </div>
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
