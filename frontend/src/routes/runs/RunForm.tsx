// SPDX-License-Identifier: Apache-2.0
// The run form (editor 4e-2b; the run form design §5.2; the Main and MoreStates boards): the published version's start
// form, live or simulated, in the Simulate dialog's look. The version it shows is the one it starts: the start goes
// with that version's id (B14), and a version published meanwhile is read and shown, the values that still fit kept.
// Each submitted form goes under one key, sent again under it only when the same form is (an answer lost on the way).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "../../components/Button";
import { TextArea } from "../../components/Field";
import { When } from "../../components/When";
import { keptValues, keyFor, refusalOf, startRun, type Refusal, type Sent, type StartBody, type StartForm } from "../../lib/runForm";
import { startFormQuery } from "../../lib/triggers";
import { SimBanner } from "../editor/simulation/SimBanner";
import { InputControl, REQUIRED, fieldKey, fromFields, hintOf, labelOf, startValues, wholeOf } from "../editor/startInput";

type Mode = StartBody["mode"];

/** A refusal says its code beside its words (the MoreStates board), but for those the form itself words. */
const CODED = (code: string) => !["version_changed", "network"].includes(code);

function ModeChoice({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const id = useId();
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 text-small font-semibold">Mode</legend>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        {(["live", "simulate"] as const).map((m) => (
          <label key={m} className="flex min-h-6 items-center gap-2 text-small">
            <input type="radio" name={`${id}-mode`} checked={mode === m} onChange={() => onChange(m)} className="size-[16px] accent-accent" />
            {m === "live" ? "Live" : "Simulated"}
          </label>
        ))}
      </div>
      {mode === "live" ? (
        <p className="rounded-lg border border-live bg-live-bg px-3 py-2 text-small text-ink">
          <strong className="text-live">Live.</strong> It acts for real: its steps call their connections, and what they
          change in Mist stays changed.
        </p>
      ) : (
        <SimBanner>
          <p>
            <strong>Simulated.</strong> Nothing is sent: actions return fixtures instead of calling out. Results don&apos;t
            prove the live call will succeed.
          </p>
        </SimBanner>
      )}
    </fieldset>
  );
}

export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, onClose }: {
  tenantId: string; workflow: { id: string; name: string }; draftDiffers?: boolean;
  onStarted: (runId: string) => void; onClose: () => void;
}) {  // prettier-ignore
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const fieldsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) d.showModal();
  }, []);
  const qc = useQueryClient();
  const read = useQuery(startFormQuery(tenantId, workflow.id));
  // The version shown is the one confirmed: a later read of the query (a refetch elsewhere) never swaps it unseen.
  const [form, setForm] = useState<StartForm | null>(null);
  if (form === null && read.data) setForm(read.data);
  const [mode, setMode] = useState<Mode>("live");
  const [values, setValues] = useState<ReadonlyMap<string, string> | null>(null);
  const shownValues = values ?? (form ? startValues(form) : new Map<string, string>());
  const [asJson, setAsJson] = useState(false);
  const [jsonText, setJsonText] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [last, setLast] = useState<Sent | null>(null);
  const [sending, setSending] = useState(false);
  const shownJson = jsonText ?? "";

  // Focus goes to the first field once the form is read (§5.6); before, the dialog holds it.
  const formRead = form !== null;
  useEffect(() => {
    if (formRead) fieldsRef.current?.querySelector<HTMLElement>("input, select, textarea")?.focus();
  }, [formRead]);

  /** What's in the fields, as JSON; a field whose value doesn't read keeps the form where it is, saying why. */
  const toJson = () => {
    if (!form) return;
    const made = fromFields(form, shownValues, false);
    if ("problems" in made) return setErrors(made.problems);
    setErrors({});
    setJsonText(Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "");
    setAsJson(true);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form || sending) return;
    let input: Record<string, unknown>;
    if (asJson) {
      const whole = wholeOf(shownJson);
      if ("problem" in whole) return setErrors({ input: whole.problem });
      input = whole.value;
    } else {
      const made = fromFields(form, shownValues, true, () => REQUIRED);
      if ("problems" in made) return setErrors(made.problems);
      input = made.input;
    }
    const body: StartBody = { input, mode, expected_version_id: form.version_id };
    const sent = keyFor(last, body);
    setLast(sent);
    setErrors({});
    setRefusal(null);
    setSending(true);
    try {
      const started = await startRun(tenantId, workflow.id, body, sent.key);
      onStarted(started.id);
    } catch (err) {
      let refused = refusalOf(err, new Set(asJson ? [] : form.fields.map((f) => f.name)));
      if (refused.code === "version_changed") {
        try {
          const fresh = await qc.query({ ...startFormQuery(tenantId, workflow.id), staleTime: 0 });
          if (fresh) {
            setValues(keptValues(shownValues, form, fresh));
            setForm(fresh);
          }
        } catch (again) {
          refused = refusalOf(again);
        }
      }
      setRefusal(refused);
      setErrors(refused.fields);
    } finally {
      setSending(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby={`${id}-title`}
      onClose={onClose}
      className="mx-auto mt-16 w-[600px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-4">
        <header>
          <h2 id={`${id}-title`} className="text-h3 font-semibold">Start a run</h2>
          <p className="text-small text-muted">{workflow.name}</p>
        </header>
        {read.isPending && form === null ? (
          <p className="text-small text-muted">Loading the published version&apos;s input…</p>
        ) : form === null ? (
          <p role="alert" className="text-small text-danger">
            {read.isError ? "The published version's input couldn't be read. Close this and start again." : "This workflow has no published version: nothing can start."}
          </p>
        ) : (
          <>
            <p className="text-small">
              <span className="text-muted">Version</span>
              {` ${form.version_number} · published `}
              <When iso={form.published_at} />
              {form.published_by ? ` by ${form.published_by}` : ""}
            </p>
            {draftDiffers && (
              <p className="text-small text-muted">
                {`The draft has changes that aren't published. This run uses version ${form.version_number}, not the draft.`}
              </p>
            )}
            <ModeChoice mode={mode} onChange={setMode} />
            <div ref={fieldsRef} className="flex flex-col gap-4">
              {asJson ? (
                <TextArea
                  label="The input, as JSON"
                  hint='An object, like {"site": "HQ"}. Shown as typed, a sensitive value too.'
                  error={errors.input}
                  value={shownJson}
                  rows={10}
                  spellCheck={false}
                  onChange={(e) => setJsonText(e.target.value)}
                />
              ) : (
                <>
                  {form.fields.length === 0 && <p className="text-small text-muted">This version takes no input.</p>}
                  {form.fields.map((f) => (
                    <InputControl
                      key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]} label={labelOf(f)} hint={hintOf(f)}
                      onChange={(v) => setValues(new Map(shownValues).set(f.name, v))}
                    />
                  ))}
                </>
              )}
            </div>
            <div>
              <Button size="sm" aria-pressed={asJson} onClick={() => (asJson ? (setAsJson(false), setJsonText(null)) : toJson())}>
                Edit as JSON
              </Button>
            </div>
          </>
        )}
        {refusal && (
          <p role="alert" className="text-small text-danger">
            {refusal.words}
            {CODED(refusal.code) && <> <span className="font-mono">{refusal.code}</span></>}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
          <Button type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending}>
            {mode === "live" ? "Start the live run" : "◌ Start the simulation"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
