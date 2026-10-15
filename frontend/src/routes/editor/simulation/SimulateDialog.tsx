// SPDX-License-Identifier: Apache-2.0
// Simulate workflow's input (4d-1c; the simulation design §7.1; the InputFields, InputJson and Narrow boards): the
// draft's own form at the revision it will send, its fields as a schedule's form enters them, or as JSON. An input in
// a Mist event's shape, or with rules no field shows, is entered as JSON from a skeleton of its schema, labelled as
// such (the catalogue keeps no examples). A draft whose input takes a CSV can't be simulated whole yet: the dialog says
// so, and that Simulate step still works. Submitting hands the input to the editor, which freezes and sends it.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "../../../components/Button";
import { TextArea } from "../../../components/Field";
import { Tag } from "../../../components/Tag";
import { inputOf, topicShaped } from "../../../lib/input";
import { draftStartFormQuery } from "../../../lib/simulations";
import { skeletonOf } from "../../../lib/skeleton";
import { triggerTypesQuery, type StartField } from "../../../lib/triggers";
import type { GraphDoc } from "../../../lib/workflows";
import { InputControl, fieldKey, fieldsShow, fromFields, nameOf, startValues, wholeOf } from "../startInput";
import { SimBanner } from "./SimBanner";

const REQUIRED = "Give a value: the input requires it.";
const SKELETON = "A generated skeleton: every field the input declares, filled with empty values of its type. Fill it with the event you want to try.";

/** A field's label, with what it is beside it, and what its hint adds: optional ones are left out when empty, sensitive
 * ones stored as protected values (the InputFields board). */
const labelOf = (f: StartField) => (
  <>
    {nameOf(f)}
    {f.required && <> <Tag>required</Tag></>}
    {f.sensitive && <> <Tag>sensitive</Tag></>}
  </>
);
const hintOf = (f: StartField) =>
  [
    f.description,
    f.required ? null : "Optional: left out when empty.",
    f.sensitive ? "Stored as a protected value: results show it as redacted." : null,
  ].filter(Boolean).join(" ") || undefined;  // prettier-ignore

export function SimulateDialog({ tenantId, workflowId, name, revision, doc, onSimulate, onClose }: {
  tenantId: string; workflowId: string; name: string; revision: number; doc: GraphDoc;
  onSimulate: (input: Record<string, unknown>) => void; onClose: () => void;
}) {  // prettier-ignore
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) d.showModal();
  }, []);
  const form = useQuery(draftStartFormQuery(tenantId, workflowId, revision));
  const types = useQuery(triggerTypesQuery);
  const schema = inputOf(doc);
  const webhook = (types.data ?? []).find((t) => Object.keys(t.topics).length > 0);
  const topic = webhook ? topicShaped(schema, webhook.topics) : null;
  const whole = topic !== null || !fieldsShow(schema); // the fields can't show it: entered as JSON
  const resolving = form.isPending || types.isPending; // how it's entered isn't known before both are read
  const [asJson, setAsJson] = useState(false);
  const json = whole || asJson;
  const [values, setValues] = useState<ReadonlyMap<string, string> | null>(null);
  const shownValues = values ?? (form.data ? startValues(form.data) : new Map<string, string>());
  const [jsonText, setJsonText] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const seeded = () => {
    if (whole) return JSON.stringify(skeletonOf(schema), null, 2);
    const made = form.data ? fromFields(form.data, shownValues, false) : { input: {} };
    return "input" in made && Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "";
  };
  const shownJson = jsonText ?? seeded();
  const csv = form.data?.csv != null;

  /** What's in the fields, as JSON; a field whose value doesn't read keeps the form where it is, saying why. */
  const toJson = () => {
    if (!form.data) return;
    const made = fromFields(form.data, shownValues, false);
    if ("problems" in made) return setErrors(made.problems);
    setErrors({});
    setJsonText(Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "");
    setAsJson(true);
  };

  function submit(e: FormEvent) {
    e.preventDefault();
    if (csv || resolving || !form.data) return;
    if (json) {
      const read = wholeOf(shownJson);
      if ("problem" in read) return setErrors({ input: read.problem });
      return onSimulate(read.value);
    }
    const made = fromFields(form.data, shownValues, true, () => REQUIRED);
    if ("problems" in made) return setErrors(made.problems);
    onSimulate(made.input);
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby={`${id}-title`}
      onClose={onClose}
      className="mx-auto mt-16 w-[560px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <form onSubmit={submit} className="flex flex-col gap-4">
        <header>
          <h2 id={`${id}-title`} className="text-h3 font-semibold">Simulate workflow</h2>
          <p className="text-small text-muted">{`${name} · draft revision ${revision}`}</p>
        </header>
        <SimBanner>
          <p>
            <strong>Simulated.</strong> Nothing is sent: actions return fixtures instead of calling out, and the other steps
            evaluate as they would live. Results don&apos;t prove the live call will succeed.
          </p>
        </SimBanner>
        {resolving ? (
          <p className="text-small text-muted">Loading the draft&apos;s input…</p>
        ) : form.isError ? (
          <p role="alert" className="text-small text-danger">The draft&apos;s input couldn&apos;t be read. Close this and simulate again.</p>
        ) : csv ? (
          <p className="text-small">
            This draft&apos;s input takes a CSV file, and a simulation can&apos;t take one yet. Its rows come only from an uploaded
            file, so the whole workflow can&apos;t be simulated until then. Simulate step still works: a step&apos;s values, rows
            included, are typed in its Test tab.
          </p>
        ) : json ? (
          <>
            <TextArea
              label={topic ? `Input, as a ${topic} event` : "The input, as JSON"}
              hint={whole ? SKELETON : 'An object, like {"site": "HQ"}. Shown as typed, a sensitive value too.'}
              error={errors.input}
              value={shownJson}
              rows={12}
              spellCheck={false}
              className="font-mono"
              onChange={(e) => setJsonText(e.target.value)}
            />
          </>
        ) : (
          <>
            {form.data.fields.length === 0 && <p className="text-small text-muted">This draft takes no input.</p>}
            {form.data.fields.map((f) => (
              <InputControl
                key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]} label={labelOf(f)} hint={hintOf(f)}
                onChange={(v) => setValues(new Map(shownValues).set(f.name, v))}
              />
            ))}
          </>
        )}
        {!resolving && !csv && !whole && form.data && (
          <div>
            <Button size="sm" aria-pressed={asJson} onClick={() => (asJson ? (setAsJson(false), setJsonText(null)) : toJson())}>
              Edit as JSON
            </Button>
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={onClose}>{csv ? "Close" : "Cancel"}</Button>
          <Button type="submit" variant="simulate" disabled={csv || resolving || form.isError}>◌ Simulate</Button>
        </div>
      </form>
    </dialog>
  );
}
