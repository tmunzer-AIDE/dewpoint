// SPDX-License-Identifier: Apache-2.0
// The message composer (4f-1, the message composer design §5): a step built on the SDK's message has it written in one
// place on Setup, the "Message" fieldset: its severity as four choices, its title, its text on several lines, its fields
// and links as numbered rows. Each part is the drawer's own field (FieldView): what's typed, held, refused or computed by
// a formula behaves as everywhere in the drawer, and a part it can't draw as its own shows today's control (ledger 102).
// Then its preview, which follows every edit (§5.5).
import { useId, useMemo, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { capWords, cutsOf, draftOf, linkProblem, slackCount, summaryOf, targetOf, TEXT_MISSING, titleHint } from "../../../lib/composer";
import { itemOf, propertiesOf, type FieldSpec } from "../../../lib/schemaForm";
import { useDrawer } from "./context";
import { FieldView, type Drawn } from "./FieldView";
import type { ControlProps } from "./scalars";
import { MessagePreview } from "./MessagePreview";
import { lineageKey, useListEdits } from "./structured";

const SEVERITIES: Record<string, string> = { info: "Info", success: "Success", warning: "Warning", critical: "Critical" };

/** The severity as four choices in a row, two rows of two at 320 px (§5.4), 44 px tall there and 24 px at least
 * beside (§5.8; in pixels, as a rem is 14 px here); unset, the model's default is chosen. */
function SeverityControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const choices = Array.isArray(spec.schema.enum) ? (spec.schema.enum as unknown[]).filter((c): c is string => typeof c === "string") : [];
  const current = typeof value === "string" ? value : typeof spec.schema.default === "string" ? spec.schema.default : "";
  return (
    // Focusable from a script, so a Go to lands on it (StepDrawer's locate).
    <div
      id={id} role="radiogroup" aria-label={spec.label} aria-describedby={describedBy} aria-invalid={invalid} tabIndex={-1}
      className="grid grid-cols-2 gap-2 sm:grid-cols-4"
    >
      {choices.map((choice) => (
        <label key={choice} className="flex min-h-[44px] items-center gap-2 rounded-lg border border-line-control px-3 text-body sm:min-h-[24px]">
          <input type="radio" name={id} value={choice} checked={current === choice} disabled={disabled} onChange={() => onChange(choice, false)} />
          {SEVERITIES[choice] ?? choice}
        </label>
      ))}
    </div>
  );  // prettier-ignore
}

const asList = (v: unknown): unknown[] => (Array.isArray(v) ? (v as unknown[]) : []);
const NEEDS_VALUE = "Each needs a label and a value.";
const NEEDS_ADDRESS = "Each needs a label and an address.";
const NARROW = "max-sm:min-h-[44px]"; // 44 px targets at 320 (§5.8), in pixels: a rem is 14 px here, so min-h-11 is 38.5

/** The fields' or the links' rows (§5.3): how many of the most, each row's label and value (or address) taking values,
 * its Move up, Move down and Remove named by its number, and Add, disabled at the most with why. */
function Rows({ spec, value, noun }: { spec: FieldSpec; value: unknown; noun: "field" | "link" }) {
  const drawer = useDrawer();
  const capId = useId();
  const items = asList(value);
  const lineage = lineageKey(value);
  const max = typeof spec.schema.maxItems === "number" ? spec.schema.maxItems : Infinity;
  const full = items.length >= max;
  const Noun = noun === "field" ? "Field" : "Link";
  const { move, remove, append } = useListEdits(spec, () => ({}));
  return (
    <>
      {Number.isFinite(max) && <p className="text-small text-muted">{items.length} of {max}</p>}
      {/* Its parts unmarked: one line says both are needed (F6, the owner's ruling). */}
      {items.length > 0 && <p className="text-small text-muted">{noun === "field" ? NEEDS_VALUE : NEEDS_ADDRESS}</p>}
      {items.map((_, i) => {
        const [label, second] = propertiesOf(itemOf(spec, i));
        const row = `${noun} ${i + 1}`;
        return (
          <div key={i} role="group" aria-label={`${Noun} ${i + 1}`} data-row-of={spec.pointer} className="flex min-w-0 flex-col gap-2">
            <div className="grid min-w-0 gap-2 sm:grid-cols-2">
              {label && <FieldView key={`${lineage}:label`} spec={{ ...label, label: `${Noun} ${i + 1} label` }} drawn={{ hint: null, quiet: true, marked: false }} />}
              {second && (
                <FieldView
                  key={`${lineage}:${second.name}`} spec={{ ...second, label: `${Noun} ${i + 1} ${noun === "field" ? "value" : "address"}` }}
                  drawn={{ hint: null, quiet: true, marked: false, check: noun === "link" ? linkProblem : undefined }}
                />
              )}
            </div>
            {drawer.editable && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" className={NARROW} aria-label={`Move up: ${row}`} disabled={i === 0} onClick={() => move(i, i - 1)}>Move up</Button>
                <Button size="sm" className={NARROW} aria-label={`Move down: ${row}`} disabled={i === items.length - 1} onClick={() => move(i, i + 1)}>
                  Move down
                </Button>
                <Button size="sm" variant="danger-outline" className={NARROW} data-remove-of={spec.pointer} aria-label={`Remove ${row}`} onClick={() => remove(i, items.length)}>
                  Remove
                </Button>
              </div>
            )}
          </div>
        );  // prettier-ignore
      })}
      {drawer.editable && (
        <>
          <Button data-add data-add-for={spec.pointer} size="sm" className={`self-start ${NARROW}`} disabled={full} aria-describedby={full ? capId : undefined} onClick={append}>
            ＋ Add a {noun}
          </Button>
          {full && <p id={capId} className="text-small text-muted">{capWords(noun, max)}</p>}
        </>
      )}
    </>
  );  // prettier-ignore
}

/** Under the text: Slack's count, or what its target would cut of it, a warning linked to it (§5.2, §5.5). */
function textDrawn(target: ReturnType<typeof targetOf>, draft: ReturnType<typeof draftOf>, cuts: ReturnType<typeof cutsOf> | null): Drawn {
  if (target === null || cuts === null) return {};
  if (target === "slack") return cuts.text ? { warn: slackCount(draft) } : { note: slackCount(draft) };
  return cuts.text ? { warn: cuts.words[0] ?? null } : {};
}

export function MessageComposer({ parts }: { parts: FieldSpec[] }) {
  const drawer = useDrawer();
  const target = targetOf(drawer.type);
  const config = drawer.node.config;
  const draft = useMemo(() => draftOf(config ?? {}), [config]);
  // What its target cuts, read once per draft: the text's words and the preview's (F6).
  const cuts = useMemo(() => (target === null ? null : cutsOf(target, draft)), [target, draft]);
  const drawnFor = (name: string): Drawn => {
    switch (name) {
      case "severity":
        return { control: SeverityControl, marked: true, hint: null }; // never empty: Info is chosen when unset (F6)
      case "title":
        return { hint: titleHint(target), quiet: true, marked: true };
      case "text":
        return { lines: true, marked: true, missing: TEXT_MISSING, ...textDrawn(target, draft, cuts) };
      case "fields":
        return { parts: (spec, value): ReactNode => <Rows spec={spec} value={value} noun="field" />, marked: true };
      case "links":
        return { parts: (spec, value): ReactNode => <Rows spec={spec} value={value} noun="link" />, marked: true };
      default:
        return {};
    }
  };
  return (
    <>
      <fieldset className="flex min-w-0 flex-col gap-4">
        <legend className="mb-1 text-body font-semibold">Message</legend>
        {/* Read only, the message as written, the rest summed up (§5.6): its preview shows them. */}
        {parts
          .filter((part) => drawer.editable || part.name === "title" || part.name === "text")
          .map((part) => (
            <FieldView key={part.pointer} spec={part} drawn={drawnFor(part.name)} />
          ))}
        {!drawer.editable && <p className="text-small">{summaryOf(config ?? {})}</p>}
      </fieldset>
      {target && <MessagePreview target={target} draft={draft} words={cuts?.words ?? []} />}
    </>
  );
}
