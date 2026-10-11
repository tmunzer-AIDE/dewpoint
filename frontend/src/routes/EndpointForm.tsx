// SPDX-License-Identifier: Apache-2.0
// A webhook endpoint's form (4c-3b; the EndpointNew, EndpointOther and NarrowForms boards). New: its name, who sends to
// it (a webhook trigger a plugin declares, Mist's, or another sender), and for another sender how it proves itself,
// where its events are and where their ids are, each fixed once it's made; then where deliveries may come from and how
// large one may be. Editing: what the API lets change, beside what was fixed when it was made.
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "../components/Button";
import { Field, Select, controlClass } from "../components/Field";
import { ApiError } from "../lib/client";
import {
  BODY_LIMITS, FIELD_WORDS, TOLERANCES, blankForm, endpointBody, endpointPatch, eventsWords, fixedWords, idsWords, proofWords, senderWords,
  type EndpointForm as Form,
} from "../lib/endpoints";  // prettier-ignore
import { createEndpoint, senderName, updateEndpoint, type Endpoint, type TriggerType } from "../lib/triggers";

type Created = Endpoint & { secret: string };

function Radio({ name, checked, label, hint, onChange, children }: {
  name: string; checked: boolean; label: string; hint?: string; onChange: () => void; children?: ReactNode;
}) {  // prettier-ignore
  return (
    <div className="flex flex-col gap-0.5">
      <label className="flex min-h-6 flex-wrap items-center gap-2 text-small">
        <input type="radio" name={name} checked={checked} onChange={onChange} className="size-[16px] accent-accent" />
        {label}
        {children}
      </label>
      {hint && <p className="pl-6 text-small text-muted">{hint}</p>}
    </div>
  );
}

function Limits({ form, set, errors }: { form: Pick<Form, "allowlist" | "bodyLimit">; set: (p: Partial<Form>) => void; errors: Record<string, string> }) {
  const id = useId();
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={id} className="text-small font-semibold">Allowed networks</label>
        <textarea
          id={id} rows={3} value={form.allowlist} spellCheck={false} aria-invalid={!!errors.allowlist}
          aria-describedby={errors.allowlist ? `${id}-hint ${id}-why` : `${id}-hint`}
          onChange={(e) => set({ allowlist: e.target.value })} className={`${controlClass(!!errors.allowlist)} py-2 font-mono text-small`}
        />
        <p id={`${id}-hint`} className="text-small text-muted">One a line, up to 32. Empty: any address.</p>
        {errors.allowlist && <p id={`${id}-why`} className="text-small text-danger">{errors.allowlist}</p>}
      </div>
      <Select label="Largest delivery" value={String(form.bodyLimit)} onChange={(e) => set({ bodyLimit: Number(e.target.value) })}>
        {BODY_LIMITS.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
        {!BODY_LIMITS.some((b) => b.value === form.bodyLimit) && <option value={form.bodyLimit}>{form.bodyLimit.toLocaleString("en-US")} bytes</option>}
      </Select>
    </>
  );  // prettier-ignore
}

/** Each field the API refused, in words; anything else in one sentence. */
function refusal(e: unknown): { fields: Record<string, string>; text: string | null } {
  if (e instanceof ApiError && e.code === "endpoint_invalid") {
    const named = ((e.body as { fields?: string[] }).fields ?? []).filter((f) => FIELD_WORDS[f]);
    return { fields: Object.fromEntries(named.map((f) => [f, FIELD_WORDS[f]!])), text: named.length > 0 ? null : "The endpoint was refused: check its fields." };
  }
  return { fields: {}, text: "The endpoint couldn't be saved. Try again." };
}

export function NewEndpoint({ tenantId, types, onCreated, onCancel }: {
  tenantId: string; types: TriggerType[]; onCreated: (made: Created) => void; onCancel: () => void;
}) {  // prettier-ignore
  const id = useId();
  const webhook = types.find((t) => Object.keys(t.topics).length > 0);
  const [form, setForm] = useState<Form>(() => blankForm(webhook?.key ?? null));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  const set = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));
  const create = useMutation({
    mutationFn: () => createEndpoint(tenantId, endpointBody(form)),
    onMutate: () => {
      setErrors({});
      setRefused(null);
    },
    onSuccess: (made) => onCreated(made),
    onError: (e) => {
      const r = refusal(e);
      setErrors(r.fields);
      setRefused(r.text);
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.name.trim() === "") return setErrors({ name: "A name, so its workflows can pick it." });
    create.mutate();
  }
  const other = form.trigger === null;
  const sender = webhook ? senderName(webhook) : null;
  return (
    <form onSubmit={submit} aria-labelledby={`${id}-title`} className="flex max-w-2xl flex-col gap-4 rounded-lg border border-line bg-surface p-4">
      <h3 id={`${id}-title`} className="text-body-lg font-semibold">New endpoint</h3>
      <Field label="Name" value={form.name} maxLength={120} error={errors.name} autoFocus onChange={(e) => set({ name: e.target.value })} />
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-small font-semibold">For</legend>
        {webhook && sender && (
          <Radio
            name={`${id}-for`} checked={!other} label={sender} onChange={() => set({ trigger: webhook.key })}
            hint={`${sender} sends a token with each event; a workflow picks one of ${sender}'s topics.`}
          />
        )}
        <Radio
          name={`${id}-for`} checked={other} label="Another sender" onChange={() => set({ trigger: null })}
          hint="You choose how it signs its events, and where a list of events and an id are."
        />
      </fieldset>
      {other && (
        <>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-small font-semibold">How it proves it&apos;s the sender · fixed once made</legend>
            <Radio name={`${id}-auth`} checked={form.auth === "bearer"} label="A token" hint="Sent in an Authorization: Bearer header." onChange={() => set({ auth: "bearer" })} />
            <Radio name={`${id}-auth`} checked={form.auth === "hmac"} label="An HMAC signature" hint="Each delivery signed with a shared secret, and timed." onChange={() => set({ auth: "hmac" })} />
            {form.auth === "hmac" && (
              <div className="flex flex-col gap-3 pl-6">
                <Field label="Signature header" value={form.signature} spellCheck={false} error={errors.signature_header} onChange={(e) => set({ signature: e.target.value })} />
                <Field label="Timestamp header" value={form.timestamp} spellCheck={false} error={errors.timestamp_header} onChange={(e) => set({ timestamp: e.target.value })} />
                <Select label="Clock difference allowed" value={String(form.tolerance)} onChange={(e) => set({ tolerance: Number(e.target.value) })}>
                  {TOLERANCES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
                </Select>
                <p className="text-small text-muted">The headers and the clock difference can change later; the kind of proof can&apos;t.</p>
              </div>
            )}
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-small font-semibold">Where the events are · fixed once made</legend>
            <Radio name={`${id}-events`} checked={form.events === "body"} label="The body is one event" onChange={() => set({ events: "body" })} />
            <Radio name={`${id}-events`} checked={form.events === "list"} label="The body is a list of events" onChange={() => set({ events: "list" })} />
            <Radio name={`${id}-events`} checked={form.events === "at"} label="A list in the body, at" onChange={() => set({ events: "at" })}>
              <input
                aria-label="The list's pointer" value={form.eventsAt} spellCheck={false} aria-invalid={!!errors.events_pointer}
                onFocus={() => set({ events: "at" })} onChange={(e) => set({ eventsAt: e.target.value })} className={`${controlClass(!!errors.events_pointer)} w-40`}
              />
            </Radio>
            <p className="text-small text-muted">A pointer into the body, like /items. At most 500 events a delivery, each matched to the workflows on its own.</p>
            {errors.events_pointer && <p className="text-small text-danger">{errors.events_pointer}</p>}
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-small font-semibold">Each event&apos;s id · fixed once made</legend>
            <Radio name={`${id}-ids`} checked={form.ids === "none"} label="None" hint="A delivery the sender repeats runs again." onChange={() => set({ ids: "none" })} />
            <Radio name={`${id}-ids`} checked={form.ids === "pointer"} label="In each event, at" onChange={() => set({ ids: "pointer" })}>
              <input
                aria-label="The id's pointer" value={form.idPointer} spellCheck={false} aria-invalid={!!errors.id_pointer}
                onFocus={() => set({ ids: "pointer" })} onChange={(e) => set({ idPointer: e.target.value })} className={`${controlClass(!!errors.id_pointer)} w-40`}
              />
            </Radio>
            <Radio name={`${id}-ids`} checked={form.ids === "header"} label="In a header" onChange={() => set({ ids: "header" })}>
              <input
                aria-label="The id's header" value={form.idHeader} spellCheck={false} aria-invalid={!!errors.id_header}
                onFocus={() => set({ ids: "header" })} onChange={(e) => set({ idHeader: e.target.value })} className={`${controlClass(!!errors.id_header)} w-40`}
              />
            </Radio>
            <p className="text-small text-muted">With an id, a delivery the sender repeats is recognized, and doesn&apos;t run twice. A pointer starts with /, like /id.</p>
            {(errors.id_pointer ?? errors.id_header) && <p className="text-small text-danger">{errors.id_pointer ?? errors.id_header}</p>}
          </fieldset>
        </>
      )}
      {other ? (
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 text-small font-semibold">Allowed addresses and the largest delivery (can change later)</legend>
          <Limits form={form} set={set} errors={errors} />
        </fieldset>
      ) : (
        <details>
          <summary className="min-h-6 cursor-pointer text-small font-semibold">Allowed addresses and the largest event</summary>
          <p className="text-small text-muted">Optional: up to 32 networks, like 203.0.113.0/24, and a size limit.</p>
          <div className="mt-3 flex flex-col gap-3">
            <Limits form={form} set={set} errors={errors} />
          </div>
        </details>
      )}
      <p className="text-small text-muted">{other ? fixedWords(form) : "How it's signed is fixed once it's made."}</p>
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={create.isPending}>Create the endpoint</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );  // prettier-ignore
}

export function EditEndpoint({ tenantId, endpoint, types, onSaved, onCancel }: {
  tenantId: string; endpoint: Endpoint; types: TriggerType[] | undefined; onSaved: () => void; onCancel: () => void;
}) {  // prettier-ignore
  const id = useId();
  const [form, setForm] = useState(() => ({
    name: endpoint.name, signature: endpoint.signature_header ?? "", timestamp: endpoint.timestamp_header ?? "", tolerance: endpoint.tolerance_s,
    allowlist: endpoint.allowlist.join("\n"), bodyLimit: endpoint.body_limit,
  }));  // prettier-ignore
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  const set = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));
  const save = useMutation({
    mutationFn: () => updateEndpoint(tenantId, endpoint.id, endpointPatch(endpoint, form)),
    onMutate: () => {
      setErrors({});
      setRefused(null);
    },
    onSuccess: onSaved,
    onError: (e) => {
      const r = refusal(e);
      setErrors(r.fields);
      setRefused(r.text);
    },
  });
  const hmac = endpoint.auth === "hmac";
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (form.name.trim() === "") return setErrors({ name: "A name, so its workflows can pick it." });
        save.mutate();
      }}
      aria-labelledby={`${id}-title`} className="flex max-w-2xl flex-col gap-4 rounded-lg border border-line bg-surface p-4"
    >
      <h3 id={`${id}-title`} className="text-body-lg font-semibold">Editing {endpoint.name}</h3>
      <Field label="Name" value={form.name} maxLength={120} error={errors.name} autoFocus onChange={(e) => set({ name: e.target.value })} />
      {hmac && (
        <>
          <Field label="Signature header" value={form.signature} spellCheck={false} error={errors.signature_header} onChange={(e) => set({ signature: e.target.value })} />
          <Field label="Timestamp header" value={form.timestamp} spellCheck={false} error={errors.timestamp_header} onChange={(e) => set({ timestamp: e.target.value })} />
          <Select label="Clock difference allowed" value={String(form.tolerance)} onChange={(e) => set({ tolerance: Number(e.target.value) })}>
            {TOLERANCES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
            {!TOLERANCES.some((x) => x.value === form.tolerance) && <option value={form.tolerance}>{form.tolerance} seconds</option>}
          </Select>
        </>
      )}
      <Limits form={form} set={set} errors={errors} />
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 rounded-lg border border-line p-3 text-small">
        <dt className="col-span-2 font-semibold">Fixed when it was made</dt>
        <dt className="text-muted">Sender</dt><dd>{senderWords(endpoint.trigger, types)}</dd>
        <dt className="text-muted">Proof</dt><dd>{proofWords(endpoint.auth)}</dd>
        <dt className="text-muted">Events</dt><dd>{eventsWords(endpoint.events_pointer)}</dd>
        <dt className="text-muted">Ids</dt><dd>{idsWords(endpoint)}</dd>
      </dl>
      <p className="text-small text-muted">To change these, make a new endpoint and move the workflows&apos; webhooks to it.</p>
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>Save</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );  // prettier-ignore
}
