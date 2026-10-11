// SPDX-License-Identifier: Apache-2.0
// The input (4c-3b; the InputFields, InputMist, InputCsv and InputEdit boards): what every trigger starts a run with,
// and, by hand, the run's form. Saved with the draft, used once published. As form fields, as a Mist event's shape (read
// only, replaceable), with a CSV file, or as JSON. Focus goes back to what opened a part once it closes (WCAG 2.4.3).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button } from "../../../components/Button";
import { csvOf, newCsv } from "../../../lib/csv";
import { addField, fieldPointer, inputOf, inputRows, setSettings, topicShaped } from "../../../lib/input";
import { senderName, triggerTypesQuery } from "../../../lib/triggers";
import { useTriggers } from "./context";
import { CsvSection } from "./CsvSection";
import { FieldEditor } from "./FieldEditor";
import { InputJson, JSON_AT } from "./InputJson";
import { MistPicker, MistShape } from "./MistEvent";
import { Problems, Section, problemsAt, useFocusBack } from "./parts";

const TYPE_WORDS: Record<string, string> = { text: "Text", whole: "Whole number", number: "Number", yesno: "Yes or no", choice: "Choice", datetime: "Date and time" };

type Mode = "fields" | "json" | "mist";

/** Where "Go to it" in the edits not applied lands: JSON, a field, or the CSV file. */
export type FocusAt = { pointer: string; n: number } | null;

export function InputSection({ focusAt }: { focusAt: FocusAt }) {
  const t = useTriggers();
  const { actions, doc } = t;
  const types = useQuery(triggerTypesQuery);
  const schema = inputOf(doc);
  const csv = csvOf(doc);
  const webhook = (types.data ?? []).find((x) => Object.keys(x.topics).length > 0);
  const shaped = webhook ? topicShaped(schema, webhook.topics) : null;
  const [mode, setMode] = useState<Mode>(() => (actions.held("json", JSON_AT) ? "json" : "fields"));
  const [editing, setEditing] = useState<string | null>(null);
  // The field being edited keeps its row through a rename, so its editor stays as it is: focus where it went, a click in
  // it landing (the review of revision 2).
  const [kept, setKept] = useState<{ name: string; key: string } | null>(null);
  const keyOf = (name: string) => (kept !== null && kept.name === name && editing === name ? kept.key : name);
  const { box, back } = useFocusBack<HTMLElement>();
  // The field "Go to it" opened on its held default: its editor opens on Default, that once. Done, another field's Edit
  // or ＋ Field clears it, so any later opening is on Name.
  const [defaultOf, setDefaultOf] = useState<string | null>(null);
  useEffect(() => {
    if (!focusAt) return;
    if (focusAt.pointer === JSON_AT) return setMode("json");
    const m = /^\/settings\/input_schema\/properties\/([^/]+)(\/default)?/.exec(focusAt.pointer);
    if (m) {
      setMode("fields");
      const name = m[1]!.replaceAll("~1", "/").replaceAll("~0", "~");
      setDefaultOf(m[2] !== undefined ? name : null);
      setEditing(name);
    }
  }, [focusAt]);
  const rows = inputRows(schema);
  const fields = rows.length; // every field the input has, the list can show it or not
  const heldJson = actions.held("json", JSON_AT);
  const add = () => {
    const made = addField(inputOf(doc));
    if (actions.update((d) => setSettings(d, { input_schema: addField(inputOf(d)).schema }), `Added the field ${made.name}.`) === null) {
      setDefaultOf(null);
      setEditing(made.name);
    }
  };
  return (
    <Section id="triggers-input" title={csv ? "Input · CSV file" : "Input"} note="Saved with the draft · used once published" box={box}>
      {mode !== "json" && <p className="text-small text-muted">Every trigger starts a run with this input. By hand, it&apos;s the run&apos;s form.</p>}
      <Problems problems={problemsAt(t.check, "/settings/input_schema", true)} />
      {heldJson && mode !== "json" && (
        <p className="text-small text-warn-ink">JSON typed here isn&apos;t saved yet: Edit as JSON shows it, with why.</p>
      )}
      {mode === "json" ? (
        <InputJson
          onBack={() => {
            setMode("fields");
            back("json");
          }}
        />
      ) : mode === "mist" && webhook ? (
        <MistPicker
          type={webhook} fields={fields}
          onDone={() => {
            setMode("fields");
            back("mist");
          }}
        />
      ) : shaped && webhook ? (
        <MistShape type={webhook} topic={shaped} onAnother={() => setMode("mist")} onJson={() => setMode("json")} onFields={() => back("add")} />
      ) : (
        <>
          {rows.length === 0 && <p className="text-small text-muted">No fields: a run starts with an empty input.</p>}
          <ul className="flex flex-col">
            {rows.map((r) => {
              const name = r.kind === "field" ? r.field.name : r.name;
              const pointer = fieldPointer(name);
              return (
                <li key={keyOf(name)} className="flex flex-col gap-2 border-t border-line py-2.5 first:border-t-0">
                  {r.kind === "field" && editing === name ? (
                    <FieldEditor
                      field={r.field} focusDefault={defaultOf === name}
                      onRenamed={(to) => {
                        setKept({ name: to, key: keyOf(name) });
                        setEditing(to);
                      }}
                      onClose={() => {
                        setEditing(null);
                        setDefaultOf(null);
                        back(`field:${name}`, "add");
                      }}
                    />
                  ) : (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="min-w-0 text-small">
                        <span className="font-mono">{name}</span>
                        {r.kind === "field" ? (
                          <>
                            {r.field.label && ` · ${r.field.label}`} · {TYPE_WORDS[r.field.type]}
                            {r.field.required ? " · required" : " · optional"}
                            {r.field.sensitive && " · sensitive"}
                          </>
                        ) : (
                          <span className="text-muted"> · {r.what}{r.required ? " · required" : ""} · read only here</span>
                        )}
                      </span>
                      {r.kind === "field" && t.editable && (
                        <Button
                          size="sm" aria-label={`Edit ${name}`} data-back={`field:${name}`}
                          onClick={() => {
                            setDefaultOf(null);
                            setEditing(name);
                          }}
                        >
                          Edit
                        </Button>
                      )}
                    </div>
                  )}
                  {editing !== name && <Problems problems={problemsAt(t.check, pointer)} />}
                  {actions.held("name", pointer) && editing !== name && (
                    <p className="text-small text-warn-ink">A new name typed for it isn&apos;t applied: Edit shows it, with why.</p>
                  )}
                </li>
              );
            })}
          </ul>
          {rows.some((r) => r.kind === "other") && (
            <p className="text-small text-muted">A field the list can&apos;t show (a list, an object of fields) appears read only: Edit as JSON changes it.</p>
          )}
          {t.editable && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" data-back="add" onClick={add}>＋ Field</Button>
              {webhook && <Button size="sm" data-back="mist" onClick={() => setMode("mist")}>Use a {senderName(webhook)} event…</Button>}
              {!csv && (
                <Button
                  size="sm" data-back="csv"
                  onClick={() => {
                    if (actions.update((d) => setSettings(d, { csv: newCsv() }), "Added a CSV file to the input.") === null) back("column:0");
                  }}
                >
                  ＋ CSV file
                </Button>
              )}
              <Button size="sm" data-back="json" onClick={() => setMode("json")}>Edit as JSON</Button>
            </div>
          )}
          {!t.editable && <Button size="sm" className="self-start" data-back="json" onClick={() => setMode("json")}>Show as JSON</Button>}
        </>
      )}
      {csv && mode !== "json" && <CsvSection csv={csv} focusAt={focusAt} back={back} />}
    </Section>
  );  // prettier-ignore
}
