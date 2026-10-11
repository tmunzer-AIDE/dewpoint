// SPDX-License-Identifier: Apache-2.0
// The input as JSON (4c-3b; the InputEdit board): the input schema and the CSV file as one text, saved with the draft
// as it's typed whenever it's JSON a save takes; text that isn't stays held, unsaved, with the line where it breaks
// (ruling 113), and text typed over an input that has since changed is written only by Apply here. The server's
// problems show with their lines. Undo works as elsewhere. It takes focus when it opens.
import { useEffect, useId, useMemo, useRef } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { csvOf } from "../../../lib/csv";
import { inputOf, sameSchema, setSettings } from "../../../lib/input";
import { inputText, lineOf, pointerWords, readInput } from "../../../lib/inputJson";
import { STALE } from "../../../lib/unapplied";
import { useText } from "../drawer/scalars";
import { useTriggers } from "./context";
import { StaleEdit, heldWhy, writeTyped } from "./parts";

/** Where the JSON text's held edit is kept, and what "Go to it" names. */
export const JSON_AT = "/settings/input";

export function InputJson({ onBack }: { onBack: () => void }) {
  const t = useTriggers();
  const { actions, doc } = t;
  const id = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => area.current?.focus(), []);
  const held = actions.held("json", JSON_AT);
  const why = heldWhy(actions, "json", JSON_AT);
  const value = useMemo(() => ({ input_schema: inputOf(doc), csv: csvOf(doc) ?? undefined }), [doc]); // a new one only when the draft changes
  const [text, setText] = useText(
    value,
    () => inputText(doc),
    (typed, v) => {
      const read = readInput(typed);
      return "value" in read && sameSchema(read.value, v);
    },
    held?.text,
  );
  const shown = held?.text ?? text;
  const problems = (t.check?.diagnostics ?? []).filter((d) => d.field !== null && /^\/settings\/(input_schema|csv)(\/|$)/.test(d.field));
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-small font-semibold">The input&apos;s schema and CSV columns</label>
      <textarea
        ref={area} id={id} value={shown} readOnly={!t.editable} rows={16} spellCheck={false} aria-describedby={`${id}-notes`}
        aria-invalid={why ? true : undefined}
        onChange={(e) => {
          const typed = e.target.value;
          setText(typed);
          const read = readInput(typed);
          const problem = "problem" in read ? (read.line === null ? read.problem : `Line ${read.line}: ${read.problem}`) : null;
          writeTyped(actions, "json", JSON_AT, { path: [], label: "The input as JSON", text: typed }, problem, () =>
            "problem" in read ? null : actions.update((d) => setSettings(d, { input_schema: read.value.input_schema, csv: read.value.csv }), null, JSON_AT),
          );  // prettier-ignore
        }}
        className={`${controlClass(!!why)} min-h-64 py-2 font-mono text-small`}
      />
      <StaleEdit kind="json" at={JSON_AT} onDiscard={() => setText(inputText(doc))} />
      <div id={`${id}-notes`} className="flex flex-col gap-1">
        {why && <p className="text-small text-danger">{why}</p>}
        {!held &&
          problems.map((d, i) => {
            const line = d.field ? lineOf(shown, d.field) : null;
            return (
              <p key={`${d.code}:${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>
                {line !== null ? `Line ${line}, ` : ""}<code className="font-mono">{pointerWords(d.field ?? "")}</code>: {d.message}
              </p>
            );
          })}
        <p className="text-small text-muted">
          {t.editable
            ? "Saved with the draft as you type, when it's JSON; text that isn't stays here, unsaved, with the line where it breaks. Undo works as elsewhere."
            : "Read only."}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={onBack}>Back to the fields</Button>
        {held && t.editable && why !== STALE && (
          <Button
            size="sm" variant="danger-outline"
            onClick={() => {
              actions.discard(JSON_AT);
              setText(inputText(doc)); // the draft's input again, as it is
            }}
          >
            Discard what isn&apos;t saved
          </Button>
        )}
      </div>
      <p className="text-small text-muted">A field the list can&apos;t show stays read only there.</p>
    </div>
  );  // prettier-ignore
}
