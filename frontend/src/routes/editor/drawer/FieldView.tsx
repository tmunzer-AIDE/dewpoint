// SPDX-License-Identifier: Apache-2.0
// One field of a step's settings (4c-1): its label; how its value is set, fixed or by a formula where the engine takes
// it, or neither (ruling 6); its control, chosen by its widget (ruling 5); the server's problems at it, with how a
// formula runs (D19); and what's typed in it but not applied, with its reason and a Discard (ruling 18). Its typing
// while it keeps focus is one undo step (ruling 8).
import { useState, type MouseEvent, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { fixedOf, formula, isPlainRef, kindOf, literal, referenceText, valueAt } from "../../../lib/config";
import { canFixed, canFormula, emptyOf, startsAsFormula, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import { STALE, type UnappliedKind } from "../../../lib/unapplied";
import { problemsAt, useDrawer, useSession } from "./context";
import { FieldFrame, GroupFrame, type Described } from "./FieldFrame";
import { FormulaControl, ModeSwitch, ReferenceView, SensitiveView, runsText, type Mode } from "./Formula";
import {
  BooleanControl, CUT_NOTE, EnumControl, JSON_NOTE, JsonControl, LITERAL_NOTE, NumberControl, TextControl,
  type ControlProps,
} from "./scalars";  // prettier-ignore
import { ContainerParts, PortControl, isContainer, partNames } from "./structured";

type Control = (props: ControlProps) => ReactNode;
const OWN: UnappliedKind[] = ["text", "json", "number", "formula", "port"]; // what a field's own control may hold
const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";

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
    default:
      return null;
  }
}

const joined = (...parts: (string | null)[]): string | null => parts.filter((p) => p !== null).join(" ") || null;

/** A pointer press on a discarding button keeps focus where it is: the edit isn't applied by the blur a click would
 * cause before it's discarded (some browsers never focus a clicked button at all). */
const keepFocus = (e: MouseEvent) => e.preventDefault();

const startMode = (spec: FieldSpec, value: unknown): Mode =>
  kindOf(value) === "cel" ? "formula"
  : value !== undefined && value !== null ? "fixed"
  : startsAsFormula(spec) ? "formula" : "fixed";  // prettier-ignore

export function FieldView({ spec }: { spec: FieldSpec }) {
  const drawer = useDrawer();
  const value = valueAt(drawer.node.config ?? {}, spec.path);
  const kind = kindOf(value);
  const empty = value === undefined || value === null;
  const [chosen, setChosen] = useState<Mode>(() => startMode(spec, value));
  const [local, setLocal] = useState<string | null>(null); // why the last write didn't happen
  const [touched, setTouched] = useState(false);
  const [asJson, setAsJson] = useState(false);
  const [generation, setGeneration] = useState(0); // a Discard starts the control afresh, from the draft
  const [seen, setSeen] = useState(value);
  if (!Object.is(seen, value)) {
    // Set elsewhere (an undo, a replace): a formula or a fixed value decides the mode; emptied, the field keeps its own.
    setSeen(value);
    setLocal(null);
    if (kind === "cel") setChosen("formula");
    else if (!empty) setChosen("fixed");
  }
  const { mark, onFocus } = useSession(`${drawer.node.id}${spec.pointer}`);
  const held = OWN.map((k) => drawer.held(k, spec.pointer)).find((u) => u !== undefined);
  const disabled = !drawer.editable;
  const fixedOk = canFixed(spec);
  const formulaOk = canFormula(spec);
  // What's held decides how the field shows, so a remount, an undo or a closed drawer never hides it (ruling 18).
  const heldMode: Mode | null = held === undefined || held.kind === "port" ? null : held.kind === "formula" ? "formula" : "fixed";
  const mode: Mode = fixedOk && formulaOk ? (heldMode ?? chosen) : fixedOk ? "fixed" : "formula"; // the engine decides
  const stale = held !== undefined && drawer.stale(held.kind, spec.pointer);
  const write = (next: unknown, typed: boolean): string | null => {
    setTouched(true);
    // Typed over what has since changed (an undo, another edit): never written there unasked (ruling 18).
    if (stale) {
      setLocal(STALE);
      return STALE;
    }
    const why = drawer.set(spec.path, next === undefined ? emptyOf(spec) : next, typed ? mark() : undefined);
    setLocal(why);
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
  const computed = kind === "ref" || kind === "template";
  const hidden = spec.sensitive && !empty && kind !== "cel"; // a fixed value in a sensitive field: never shown (M25)
  const fixed = fixedOf(value);
  // A literal's or an unreadable envelope's parts aren't where a form writes them: shown as JSON.
  const json = asJson || held?.kind === "json" || kind === "unknown" || (kind === "literal" && isContainer(spec.base));
  const container = mode === "fixed" && fixedOk && !computed && !hidden && !json && isContainer(spec.base);
  const problems = problemsAt(drawer.problems, spec.pointer, container ? new Set(partNames(spec, fixed)) : null);
  const required = spec.required && !spec.entry && spec.path.length > 1;
  const missing = spec.required && touched && (empty || value === "") ? "Required" : null;
  const switchTo = (next: Mode) =>
    reshape(
      (current) => {
        if (next === "fixed") return kindOf(current) === "cel" ? emptyOf(spec) : current;
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
    write(undefined, false);
  };
  const actions = (
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} />
      )}
      {mode === "fixed" && fixedOk && !computed && !hidden && kind === null && isContainer(spec.base) && !spec.holdsSensitive && (
        <Button size="sm" aria-pressed={json} onClick={toggleJson}>Edit as JSON</Button>
      )}
      {!disabled && held && stale && (
        <Button
          size="sm"
          aria-label={`Apply here: ${spec.label}`}
          onClick={() => {
            drawer.rebase(held.kind, spec.pointer);
            setLocal(drawer.apply(held.kind, spec.pointer));
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
          }}
        >
          Discard
        </Button>
      )}
      {!disabled && !spec.required && !spec.entry && value !== undefined && (
        <Button size="sm" aria-label={`Clear ${spec.label}`} onMouseDown={keepFocus} onClick={clear}>Clear</Button>
      )}
    </>
  );
  const frame = (control: (c: Described) => ReactNode, hint: string | null = spec.hint, below?: ReactNode) => (
    <FieldFrame label={spec.label} required={required} hint={hint} local={stale ? STALE : (held?.why ?? local ?? missing)} problems={problems} actions={actions} below={below}>
      {control}
    </FieldFrame>
  );
  const Control: Control = json
    ? JsonControl
    : spec.port
      ? PortControl
      : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  const Held = held ? heldControl(held.kind, spec) : null;
  let body: ReactNode;
  if (held && Held) {
    // What's held shows first, before what the value under it has become (a reference, a hidden secret, another
    // mode): it stays visible, and recoverable, until it's applied or discarded (the review of revision 3).
    body = frame(
      (c) => (
        <Held
          key={generation} {...c} spec={spec} value={hidden ? undefined : held.kind === "formula" ? value : fixed}
          literal={held.literal ?? false} disabled={disabled} onChange={held.kind === "formula" ? write : writeFixed}
        />
      ),
      joined(spec.hint, held.literal ? LITERAL_NOTE : held.kind === "json" ? JSON_NOTE : null),
    );  // prettier-ignore
  } else if (hidden) {
    body = frame((c) => (
      <SensitiveView
        {...c} toFormula={formulaOk} disabled={disabled}
        onClear={clear}
        onFormula={() => reshape(() => emptyOf(spec), () => setChosen("formula"))}
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
      joined(spec.hint, NEITHER),
    );
  } else if (computed) {
    body = frame((c) => (
      <ReferenceView
        {...c} value={value} fixed={fixedOk} toFormula={formulaOk} disabled={disabled}
        onFixed={() => reshape(() => emptyOf(spec), () => setChosen("fixed"))}
        onFormula={() => reshape(() => (isPlainRef(value) ? formula(referenceText(value)) : emptyOf(spec)), () => setChosen("formula"))}
      />
    ));  // prettier-ignore
  } else if (mode === "formula") {
    const runs = runsText(drawer.expressions.find((x) => x.field === spec.pointer));
    body = frame(
      (c) => <FormulaControl key={generation} {...c} spec={spec} value={value} literal={false} disabled={disabled} onChange={write} />,
      spec.hint,
      runs && <p className="text-small text-muted">{runs}</p>,
    );
  } else if (container) {
    body = (
      <GroupFrame label={spec.label} required={required} hint={spec.hint} local={local ?? missing} problems={problems} actions={actions}>
        <ContainerParts spec={spec} value={fixed} />
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
      joined(spec.hint, note),
    );
  }
  return (
    // The field is one focus region: what's typed in JSON or a port's name applies when focus leaves the region, so
    // moving to its own Discard or Clear, by keyboard or pointer, never applies it first (the review of revision 4).
    <div
      data-pointer={spec.pointer}
      onFocus={onFocus}
      onBlur={(e) => {
        if (e.currentTarget.contains(e.relatedTarget)) return;
        if (held && (held.kind === "json" || held.kind === "port")) drawer.apply(held.kind, spec.pointer);
      }}
    >
      {body}
    </div>
  );
}
