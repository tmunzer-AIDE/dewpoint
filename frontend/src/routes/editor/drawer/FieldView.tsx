// SPDX-License-Identifier: Apache-2.0
// One field of a step's settings (4c-1): its label; how its value is set, fixed or by a formula where the engine takes
// it, or neither (ruling 6); its control, chosen by its widget (ruling 5); the server's problems at it, with how a
// formula runs (D19); and what's typed in it but not applied, with its reason and a Discard (ruling 18). Its typing
// while it keeps focus is one undo step (ruling 8).
import { useContext, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { fixedOf, formula, isEmptyValue, isPlainRef, kindOf, literal, referenceText, valueAt } from "../../../lib/config";
import { segmentsOf, type Caret } from "../../../lib/pills";
import { canFixed, canFormula, emptyOf, startsAsFormula, takesPills, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import { STALE, empties, type Unapplied, type UnappliedKind } from "../../../lib/unapplied";
import { EmptiedContext, problemsAt, useDrawer, useSession } from "./context";
import { FieldFrame, GroupFrame, type Described } from "./FieldFrame";
import { FormulaControl, ModeSwitch, ReferenceView, SensitiveView, runsText, type Mode } from "./Formula";
import { ChoicesBelow, OptionsControl } from "./LiveOptions";
import { ConnectionControl, WorkflowControl } from "./pickers";
import {
  BooleanControl, CUT_NOTE, EnumControl, JSON_NOTE, JsonControl, LITERAL_NOTE, NumberControl, TextControl,
  type ControlProps,
} from "./scalars";  // prettier-ignore
import { ContainerParts, PortControl, isContainer, partNames } from "./structured";
import { ConditionBuilder, conditionOf } from "./ConditionBuilder";
import { TextPills, type Opened } from "./TextPills";

type Control = (props: ControlProps) => ReactNode;
const OWN: UnappliedKind[] = ["text", "template", "condition", "json", "number", "formula", "port"]; // what a field's own control may hold
const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";
export const PILLS_NOTE = "Press / or ＋ Data to insert data from earlier steps. A dashed pill may be missing when this runs: give it a default.";
/** What a text on several lines says, under the message's text (4f-1). */
export const LINES_NOTE = "Press / or ＋ Data to add a value; Enter starts a new line.";
/** Under a field that takes values and has choices (4f-2, ruling 127 amended). */
export const CHOICES_NOTE = "A value from an earlier step, or one of the connection's choices: Show choices lists them.";
/** What a viewer and a version's view are told: they can't insert data or give a default (#85). */
export const PILLS_SEEN = "A dashed pill may be missing when this runs.";

/** The control for what's held, of this kind: it shows first, whatever the value under it has become (ruling 18). A
 * field with live choices keeps its own control, so its choices stay a click away. */
function heldControl(kind: UnappliedKind, spec: FieldSpec): Control | null {
  switch (kind) {
    case "text":
      return (spec.widget === "options" ? controlFor("options") : null) ?? TextControl;
    case "number":
      return NumberControl;
    case "json":
      return JsonControl;
    case "formula":
      return FormulaControl;
    case "port":
      return PortControl;
    default:
      return null;
  }
}

/** The control for a fixed value of this widget, or null when the drawer has none: its type's is used then. */
function controlFor(widget: Widget): Control | null {
  switch (widget) {
    case "text":
    case "datetime":
      return TextControl;
    case "number":
    case "integer":
      return NumberControl;
    case "boolean":
      return BooleanControl;
    case "enum":
      return EnumControl;
    case "json":
      return JsonControl;
    case "connection":
      return ConnectionControl;
    case "workflow":
      return WorkflowControl;
    case "options":
      return OptionsControl;
    default:
      return null;
  }
}

const joined = (...parts: (string | null)[]): string | null => parts.filter((p) => p !== null).join(" ") || null;

/** A pointer press on a discarding button keeps focus where it is: the edit isn't applied by the blur a click would
 * cause before it's discarded (some browsers never focus a clicked button at all). */
const keepFocus = (e: MouseEvent) => e.preventDefault();

/** A condition the builder writes (4c-2b): a formula field that gives true or false. */
const builds = (spec: FieldSpec): boolean => spec.widget === "formula" && spec.base === "boolean" && canFormula(spec);

const startMode = (spec: FieldSpec, value: unknown, fixed = false): Mode =>
  builds(spec) ? (conditionOf(value) !== null || typeof value === "boolean" ? "fixed" : "formula")
  : kindOf(value) === "cel" ? "formula"
  : takesPills(spec) && segmentsOf(value) !== null && value !== undefined && value !== null ? "fixed"
  : value !== undefined && value !== null ? "fixed"
  : startsAsFormula(spec) && !fixed ? "formula" : "fixed";  // prettier-ignore

/** How the message composer draws one of its parts (4f-1, the message composer design §5): its own control (the
 * severity's choices) or its own rows (the fields', the links'), the text on several lines, a check said as it's typed
 * (a link's address), its hint in place of the schema's, a described note after it (Slack's count), without the note on
 * pills (`quiet`), "(required)" said or not whatever its level (`marked`: Setup holds optional parts too; a row's parts go
 * unmarked, F6), a warning (what its target would cut) and what's said under it. */
export interface Drawn {
  control?: Control;
  parts?: (spec: FieldSpec, value: unknown) => ReactNode;
  lines?: boolean;
  check?: (value: unknown) => string | null;
  hint?: string | null;
  note?: string | null; // said after the hint, described (Slack's count, F6)
  quiet?: boolean;
  marked?: boolean;
  missing?: string; // said in place of "Required"
  warn?: string | null;
  below?: ReactNode;
  // An update's changes and a create's settings (4f-2b): drawn as a group of `parts` even when it's a union (`group`),
  // empty in Fixed (`startFixed`: a union is Set as JSON), its fixed side named ("List"), the parts it draws (`shown`:
  // a problem at another stays on the group), its setting's name beside its label, its own actions, no Clear.
  group?: boolean;
  startFixed?: boolean;
  fixedName?: string;
  shown?: string[];
  name?: string;
  actions?: ReactNode;
  hideClear?: boolean;
  switchLabel?: string; // what its Fixed | Formula switch says it sets, when its label doesn't read well there
  rowOf?: string; // the list it's a row of: a Remove beside it lands on the row taking its place (F6)
}

export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn }) {
  const drawer = useDrawer();
  const emptied = useContext(EmptiedContext);
  const value = valueAt(drawer.node.config ?? {}, spec.path);
  const kind = kindOf(value);
  const empty = value === undefined || value === null;
  const [chosen, setChosen] = useState<Mode>(() => startMode(spec, value, drawn.startFixed));
  const [local, setLocal] = useState<string | null>(null); // why the last write didn't happen
  const [touched, setTouched] = useState(false);
  const [asJson, setAsJson] = useState(false);
  const [generation, setGeneration] = useState(0); // a Discard starts the control afresh, from the draft
  const [seen, setSeen] = useState(value);
  if (!Object.is(seen, value)) {
    // Set elsewhere (an undo, a replace): a formula or a fixed value decides the mode; emptied, the field keeps its own.
    setSeen(value);
    setLocal(null);
    // A condition the builder can show stays in the builder: what it writes is a formula too (4c-2b).
    if (builds(spec)) setChosen((m) => (m === "fixed" && conditionOf(value) === null && typeof value !== "boolean" ? "formula" : m));
    else if (kind === "cel") setChosen("formula");
    else if (!empty) setChosen("fixed");
  }
  const { mark, onFocus } = useSession(`${drawer.node.id}${spec.pointer}`);
  const region = useRef<HTMLDivElement>(null);
  /** After one of the field's own actions, which removes the button pressed or remounts the control: focus goes back to
   * the field's control, else its first one (WCAG 2.4.3; the final review). */
  const refocus = () =>
    requestAnimationFrame(() => {
      const box = region.current;
      const label = box?.querySelector<HTMLLabelElement>("label[for]");
      const control = label ? document.getElementById(label.htmlFor) : null;
      const usable = control && control.tagName !== "OUTPUT" && !(control as HTMLInputElement).disabled ? control : null;
      // A list or a map emptied has no control left, only its Add (the review of 97235e3).
      (usable ??
        box?.querySelector<HTMLElement>("input:not([disabled]), textarea:not([disabled]), select:not([disabled])") ??
        box?.querySelector<HTMLElement>("[data-add]:not([disabled])"))?.focus();
    });
  const held = OWN.map((k) => drawer.held(k, spec.pointer)).find((u) => u !== undefined);
  const disabled = !drawer.editable;
  // Text with data pills: its fixed mode where the engine takes a template (4c-2b), whatever its kinds say of literals.
  const pills = takesPills(spec);
  const asText = pills && segmentsOf(value) !== null;
  const [opened, setOpened] = useState<Opened | null>(null);
  const caret = useRef<Caret | null>(null);
  const focusNext = useRef<{ segment: number; offset: number } | { pill: number } | null>(null);
  const builder = builds(spec);
  const buildable = builder && (conditionOf(value) !== null || typeof value === "boolean");
  const whyNotId = `${spec.pointer}-why-not-builder`;
  const fixedOk = canFixed(spec) || pills || builder;
  const formulaOk = canFormula(spec);
  // What's held decides how the field shows, so a remount, an undo or a closed drawer never hides it (ruling 18).
  const heldMode: Mode | null = held === undefined || held.kind === "port" ? null : held.kind === "formula" ? "formula" : "fixed";
  // A formula the builder didn't write stays a formula (the mockups' formula board).
  const mode: Mode = fixedOk && formulaOk ? (heldMode ?? chosen) : fixedOk ? "fixed" : "formula"; // the engine decides
  const stale = held !== undefined && drawer.stale(held.kind, spec.pointer);
  const write = (next: unknown, typed: boolean): string | null => {
    setTouched(true);
    // Typed over what has since changed (an undo, another edit): never written there unasked (ruling 18).
    if (stale) {
      setLocal(STALE);
      return STALE;
    }
    const value = next === undefined ? emptyOf(spec) : next;
    const why = drawer.set(spec.path, value, typed ? mark() : undefined);
    setLocal(why);
    if (why === null && isEmptyValue(value)) emptied?.(); // cleared or emptied, it stays drawn while typed in (F1)
    return why;
  };
  // What's held, applied: emptied by it, the field stays drawn all the same (F1).
  const apply = (u: Unapplied): string | null => {
    const why = drawer.apply(u.kind, spec.pointer);
    if (why === null && empties(u)) emptied?.();
    return why;
  };
  // A literal's payload is written back as a literal: its kind changes only on purpose (ruling 15). An edit begun as a
  // literal's keeps that reading.
  const asLiteral = held?.literal ?? kind === "literal";
  const writeFixed = (next: unknown, typed: boolean) => write(next !== undefined && asLiteral ? literal(next) : next, typed);
  /** A change to the whole value: what's typed beneath it is applied first, or the change waits (ruling 18). */
  const reshape = (make: (current: unknown) => unknown, then: () => void) => {
    const why = drawer.restructure(spec.pointer, { path: spec.path, make });
    setLocal(why);
    if (why === null) then();
  };
  const computed = (kind === "ref" || kind === "template") && !asText;
  // A fixed value in a sensitive field: never shown (M25). A reference or a template there is how a secret is passed,
  // and shows as one (the final review).
  const hidden = spec.sensitive && !empty && kind !== "cel" && !computed;
  const fixed = fixedOf(value);
  // A literal's or an unreadable envelope's parts aren't where a form writes them: shown as JSON.
  const json = asJson || held?.kind === "json" || kind === "unknown" || (kind === "literal" && isContainer(spec.base));
  const container = mode === "fixed" && fixedOk && !computed && !hidden && !json && (isContainer(spec.base) || drawn.group === true);
  const problems = problemsAt(drawer.problems, spec.pointer, container ? new Set(drawn.shown ?? partNames(spec, fixed)) : null);
  const required = spec.required && !spec.entry && (drawn.marked ?? spec.path.length > 1);
  const hint = drawn.hint !== undefined ? drawn.hint : spec.hint;
  const checked = drawn.check?.(value) ?? null; // said where a refusal would be, after it
  // A list's item or a map's entry, emptied, keeps its place, blank: never missing on its own (the final review).
  const missing = spec.required && !spec.entry && touched && (empty || value === "") ? (drawn.missing ?? "Required") : null;
  const switchTo = (next: Mode) =>
    builder
      ? reshape((current) => current, () => setChosen(next)) // the same formula, shown the other way
      : reshape(
      (current) => {
        if (next === "fixed") return kindOf(current) === "cel" ? emptyOf(spec) : current;
        // A lone reference becomes its path; text with pills starts an empty formula (Undo brings it back): text
        // around references isn't a formula (4c-2b).
        if (isPlainRef(current)) return formula(referenceText(current));
        if (kindOf(current) === "ref" || kindOf(current) === "template") return emptyOf(spec);
        const was = fixedOf(current);
        // A fixed value becomes the formula that gives it, unless it holds a sensitive part: never copied into visible
        // text (M25), the formula starts empty.
        return was === undefined || was === null || spec.holdsSensitive ? emptyOf(spec) : formula(JSON.stringify(was));
      },
      () => setChosen(next),
    );
  const toggleJson = () => {
    const why = drawer.restructure(spec.pointer); // what's typed in one view is applied before the other shows
    setLocal(why);
    if (why === null) setAsJson(!json); // from what shows: held JSON shows as JSON whatever `asJson` says
  };
  const clear = () => {
    drawer.discard(spec.pointer); // Clear drops what's typed in it too, on purpose (ruling 18)
    setGeneration((g) => g + 1);
    setTouched(true);
    // Written over what's there now: the stale edit `write` guards against is discarded above, so this render's
    // `stale` no longer applies. The editor's own guards (read only, admission) still answer (the review of milestone 2).
    setLocal(drawer.set(spec.path, emptyOf(spec)));
    refocus();
  };
  const actions = (
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch
          label={drawn.switchLabel ?? spec.label} mode={mode} disabled={disabled} onChange={switchTo} fixedName={drawn.fixedName ?? (pills ? "Text" : builder ? "Builder" : "Fixed")}
          fixedWhyNot={builder && !buildable && held?.kind !== "condition" ? { id: whyNotId } : null}
        />
      )}
      {builder && !buildable && mode === "formula" && (
        <p id={whyNotId} className="w-full text-small text-muted">
          This formula wasn&apos;t made with the builder, so it stays a formula: the builder opens only what it wrote. Clear it to
          start one in the builder.
        </p>
      )}
      {pills && mode === "fixed" && !disabled && drawer.revision !== null && (
        <Button
          size="sm" aria-haspopup="dialog" aria-expanded={opened?.kind === "tree"}
          onClick={() => setOpened(opened?.kind === "tree" ? null : { kind: "tree", at: caret.current ?? { segment: Infinity, offset: Infinity }, slash: false })}
        >
          ＋ Data
        </Button>
      )}
      {mode === "fixed" && fixedOk && !computed && !hidden && kind === null && isContainer(spec.base) && !spec.holdsSensitive && !drawn.parts && (
        // Pressed as Segmented's options are, by weight and fill from its tokens, while it's on (the owner's ruling O1).
        <Button
          size="sm" aria-pressed={json} onClick={toggleJson}
          className="aria-pressed:bg-accent-soft aria-pressed:font-semibold aria-pressed:text-accent-ink"
        >
          Edit as JSON
        </Button>
      )}
      {!disabled && held && stale && (
        <Button
          size="sm"
          aria-label={`Apply here: ${spec.label}`}
          onClick={() => {
            drawer.rebase(held.kind, spec.pointer);
            setLocal(apply(held));
            refocus();
          }}
        >
          Apply here
        </Button>
      )}
      {!disabled && held && (
        <Button
          size="sm"
          aria-label={`Discard the edit to ${spec.label}`}
          onMouseDown={keepFocus}
          onClick={() => {
            drawer.release(held.kind, spec.pointer);
            setGeneration((g) => g + 1);
            setLocal(null);
            refocus();
          }}
        >
          Discard
        </Button>
      )}
      {!disabled && !spec.required && !spec.entry && value !== undefined && drawn.hideClear !== true && (
        <Button size="sm" aria-label={`Clear ${spec.label}`} onMouseDown={keepFocus} onClick={clear}>Clear</Button>
      )}
      {drawn.actions}
    </>
  );
  const frame = (control: (c: Described) => ReactNode, said: string | null = hint, below: ReactNode = drawn.below) => (
    <FieldFrame label={spec.label} name={drawn.name} required={required} hint={said} note={drawn.note} warn={drawn.warn} local={stale ? STALE : (held?.why ?? local ?? missing ?? checked)} problems={problems} actions={actions} below={below}>
      {control}
    </FieldFrame>
  );
  const Control: Control = json
    ? JsonControl
    : spec.port
      ? PortControl
      : (drawn.control ?? controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  const Held = held && held.kind !== "template" ? heldControl(held.kind, spec) : null;
  // A decision that reads sensitive data (the server's taint.undeclassified, under its field): the list where it's
  // declassified is a click away (4c-2b, the builder's and the formula's boards).
  const declassifiable = drawer.openDeclassify && problems.some((d) => d.code === "taint.undeclassified") && (
    <div><Button size="sm" onClick={drawer.openDeclassify}>Review in Declassify…</Button></div>
  );
  const panel = { opened, open: setOpened, caret, focus: focusNext };
  const textPills = (c: Described) => (
    <TextPills
      key={generation} {...c} spec={spec} value={hidden ? undefined : fixed} literal={held?.literal ?? kind === "literal"}
      disabled={disabled} onChange={write} panel={panel} lines={drawn.lines} // it writes a literal back as one itself, never a template as data
    />
  );  // prettier-ignore
  let body: ReactNode;
  let says = false; // how its formula runs, said under it
  if (held?.kind === "condition" || (builder && mode === "fixed" && buildable && !(held && Held))) {
    // The condition builder (4c-2b): what's held, or the value, as comparisons.
    const runs = runsText(drawer.expressions.find((x) => x.field === spec.pointer));
    says = runs !== null;
    body = (
      <GroupFrame
        label={spec.label} required={required} hint={hint} local={held?.why ?? local ?? missing} problems={problems} actions={actions}
        below={<>{runs && <p className="text-small text-muted">{runs}</p>}{declassifiable}</>}
      >
        <ConditionBuilder key={generation} spec={spec} value={value} disabled={disabled} onChange={write} />
      </GroupFrame>
    );  // prettier-ignore
  } else if (held?.kind === "template" || (mode === "fixed" && asText && !hidden && !(held && Held))) {
    // Text with data pills: what's held, or the value, as text and pills (4c-2b).
    // "/" and "＋ Data" work where the person may edit the draft: the note says them only there (#85).
    const pillsNote = drawn.quiet ? null : disabled || drawer.revision === null ? PILLS_SEEN : drawn.lines ? LINES_NOTE : PILLS_NOTE;
    const choosing = spec.widget === "options";
    // Its choices under it: a pick replaces what's there, as text (4f-2). The query is its written text, if it's only that.
    const written = segmentsOf(value);
    const choices = choosing && (
      <ChoicesBelow
        spec={spec} query={written !== null && written.pills.length === 0 ? written.texts.join("") : ""} current={value} disabled={disabled}
        onDone={refocus}
        onPick={(choice) => {
          const why = writeFixed(choice, false);
          if (why === null) {
            drawer.release("template", spec.pointer);
            setGeneration((g) => g + 1);
          }
          return why;
        }}
      />
    );  // prettier-ignore
    body = frame(
      textPills,
      joined(hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, choosing ? CHOICES_NOTE : null, pillsNote),
      choices ? <>{drawn.below}{choices}</> : drawn.below,
    );
  } else if (held && Held) {
    // What's held shows first, before what the value under it has become (a reference, a hidden secret, another
    // mode): it stays visible, and recoverable, until it's applied or discarded (the review of revision 3).
    body = frame(
      (c) => (
        <Held
          key={generation} {...c} spec={spec} value={hidden ? undefined : held.kind === "formula" ? value : fixed}
          literal={held.literal ?? false} disabled={disabled} onChange={held.kind === "formula" ? write : writeFixed}
        />
      ),
      joined(hint, held.literal ? LITERAL_NOTE : held.kind === "json" ? JSON_NOTE : null),
    );  // prettier-ignore
  } else if (hidden) {
    body = frame((c) => (
      <SensitiveView
        {...c} toFormula={formulaOk} disabled={disabled}
        onClear={clear}
        onFormula={() => reshape(() => emptyOf(spec), () => {
          setChosen("formula");
          refocus();
        })}
      />
    ));  // prettier-ignore
  } else if (!fixedOk && !formulaOk) {
    // Only references or templates (4c-2's pills): what's there is shown, nothing is offered (ruling 6).
    body = frame(
      (c) => (
        <output id={c.id} aria-describedby={c.describedBy} className="block break-all font-mono text-small">
          {computed ? referenceText(value) : empty ? "Not set" : "A value this field doesn't take"}
        </output>
      ),
      joined(hint, NEITHER),
    );
  } else if (computed) {
    body = frame((c) => (
      <ReferenceView
        {...c} value={value} fixed={fixedOk} toFormula={formulaOk} disabled={disabled}
        onFixed={() => reshape(() => emptyOf(spec), () => {
          setChosen("fixed");
          refocus();
        })}
        onFormula={() => reshape(() => (isPlainRef(value) ? formula(referenceText(value)) : emptyOf(spec)), () => {
          setChosen("formula");
          refocus();
        })}
      />
    ));  // prettier-ignore
  } else if (mode === "formula") {
    const runs = runsText(drawer.expressions.find((x) => x.field === spec.pointer));
    says = runs !== null;
    body = frame(
      (c) => <FormulaControl key={generation} {...c} spec={spec} value={value} literal={false} disabled={disabled} onChange={write} />,
      hint,
      <>
        {runs && <p className="text-small text-muted">{runs}</p>}
        {declassifiable}
        {drawn.below}
      </>,
    );
  } else if (container) {
    body = (
      <GroupFrame label={spec.label} name={drawn.name} required={required} hint={hint} warn={drawn.warn} local={local ?? missing} problems={problems} actions={actions} below={drawn.below}>
        {drawn.parts ? drawn.parts(spec, fixed) : <ContainerParts spec={spec} value={fixed} />}
      </GroupFrame>
    );
  } else if (spec.holdsSensitive && Control === JsonControl) {
    body = frame((c) => (
      <output id={c.id} aria-describedby={c.describedBy} className="block text-small">
        It holds a sensitive part, so it isn&apos;t shown as JSON.
      </output>
    ));
  } else {
    const note = kind === "literal" ? LITERAL_NOTE : Control === JsonControl ? (spec.cut ? `${CUT_NOTE} ${JSON_NOTE}` : JSON_NOTE) : null;
    body = frame(
      (c) => (
        <Control key={generation} {...c} spec={spec} value={fixed} literal={kind === "literal"} disabled={disabled} onChange={writeFixed} />
      ),
      joined(hint, note),
    );
  }
  // Said here, so the drawer's list of how its formulas run leaves it out (the owner's ruling O4).
  const explains = drawer.explains;
  useEffect(() => (says && explains ? explains(spec.pointer) : undefined), [says, explains, spec.pointer]);
  return (
    // The field is one focus region: what's typed in JSON or a port's name applies when focus leaves the region, so
    // moving to its own Discard or Clear, by keyboard or pointer, never applies it first (the review of revision 4).
    <div
      ref={region}
      data-pointer={spec.pointer}
      data-row-of={drawn.rowOf}
      onFocus={onFocus}
      onBlur={(e) => {
        if (e.currentTarget.contains(e.relatedTarget)) return;
        if (held && (held.kind === "json" || held.kind === "port")) apply(held);
      }}
    >
      {body}
    </div>
  );
}
