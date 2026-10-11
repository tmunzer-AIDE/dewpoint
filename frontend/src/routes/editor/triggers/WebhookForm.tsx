// SPDX-License-Identifier: Apache-2.0
// A webhook's form (4c-3b; the Webhooks and NarrowForms boards): an endpoint, and when this workflow runs for its
// events. A webhook trigger's endpoint picks one of its topics, and may give the input the topic's shape, in the draft;
// another sender's runs for events where up to 8 conditions hold. Saved at once. Editing one changes its conditions,
// or removes it, asked first (the binding's form, extrapolated from the boards: ruling proposed). A binding is shown
// as it is: by its topic only when its filter is that topic alone, else by its conditions, each value as typed back
// exactly; nothing shows before the endpoint's sender is known (the review of revision 1), and when that can't be
// loaded, it says so and offers to try again, never conditions in its topic's place (the review of revision 2).
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type FormEvent } from "react";
import { Button } from "../../../components/Button";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Select, controlClass } from "../../../components/Field";
import { announce } from "../../../lib/announce";
import { ApiError } from "../../../lib/client";
import { inputOf, inputRows, sameSchema, setSettings } from "../../../lib/input";
import {
  createBinding, deleteBinding, endpointsQuery, parseValue, possessive, senderName, topicOf, triggerTypesQuery, updateBinding, valueText,
  workflowBindingsQuery, type FilterClause, type WorkflowBinding,
} from "../../../lib/triggers";  // prettier-ignore
import { useTriggers } from "./context";
import { Check } from "./parts";

const MAX_CLAUSES = 8;

const REFUSALS: Record<string, string> = {
  binding_exists: "This endpoint already starts this workflow.",
  binding_cap: "This endpoint starts 20 workflows, its most: remove one there first.",
  filter_invalid: "The endpoint refuses these conditions: each field is a pointer starting with /, each value a text of at most 1,024 characters, a whole number, true, false or null.",
  not_found: "This endpoint is gone: choose another.",
};

type Clause = { pointer: string; value: string };

export function WebhookForm({ binding, onDone }: { binding: WorkflowBinding | null; onDone: (saved: boolean) => void }) {
  const t = useTriggers();
  const id = useId();
  const editing = binding !== null;
  const types = useQuery(triggerTypesQuery);
  const endpoints = useQuery({ ...endpointsQuery(t.tenantId), enabled: !editing });
  const bound = useQuery(workflowBindingsQuery(t.tenantId, t.workflowId));
  const taken = new Set((bound.data?.bindings ?? []).map((b) => b.endpoint_id));
  const choices = endpoints.data?.endpoints ?? [];
  const [endpointId, setEndpointId] = useState<string | null>(binding?.endpoint_id ?? null);
  const chosen = editing ? binding.endpoint : (choices.find((e) => e.id === endpointId) ?? null);
  const type = chosen ? (types.data ?? []).find((x) => x.key === chosen.trigger) : undefined;
  const topics = type ? Object.keys(type.topics) : [];
  // What the endpoint sends decides how the form shows its filter: a sender's endpoint waits for it to load.
  const needsTypes = chosen !== null && chosen.trigger !== null;
  const ready = !needsTypes || types.isSuccess;
  // By its topic: a new one for a sender with topics, or one whose filter is a topic alone; else by its conditions.
  const byTopic = !!type && topics.length > 0 && (!editing || topicOf(binding.filter, type) !== null);
  const [topic, setTopic] = useState<string | null>(null); // chosen here; until then, the binding's or the first
  const shownTopic = !byTopic ? null : topic !== null && topics.includes(topic) ? topic : editing ? topicOf(binding.filter, type) : (topics[0] ?? null);
  const [useShape, setUseShape] = useState(true);
  const [clauses, setClauses] = useState<Clause[]>(() => (binding?.filter ?? []).map((c) => ({ pointer: c.pointer, value: valueText(c.value) })));
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const fields = inputRows(inputOf(t.doc)).length;
  const shaped = byTopic && type && shownTopic ? sameSchema(inputOf(t.doc), type.topics[shownTopic]) : false;
  const offerShape = byTopic && !!shownTopic && t.editable && !shaped;

  /** The conditions as the API takes them, or each one's problem. */
  function filter(): FilterClause[] | null {
    if (byTopic && type && shownTopic) return [{ pointer: type.topic_pointer, value: shownTopic }];
    const found: Record<number, string> = {};
    const out: FilterClause[] = [];
    clauses.forEach((c, i) => {
      const read = parseValue(c.value);
      if (!c.pointer.startsWith("/") || c.pointer.length > 256) found[i] = "A field is a pointer into the event, starting with /, like /type.";
      else if ("problem" in read) found[i] = read.problem;
      else out.push({ pointer: c.pointer, value: read.value });
    });
    setErrors(found);
    return Object.keys(found).length > 0 ? null : out;
  }

  const save = useMutation({
    mutationFn: (f: FilterClause[]) =>
      editing
        ? updateBinding(t.tenantId, binding.id, { filter: f })
        : createBinding(t.tenantId, chosen!.id, { workflow_id: t.workflowId, filter: f }),
    onMutate: () => setRefused(null),
    onSuccess: () => {
      if (!editing && offerShape && useShape && type && shownTopic) {
        const shape = type.topics[shownTopic];
        t.actions.update((d) => setSettings(d, { input_schema: shape }), `The input is now ${possessive(shownTopic)} shape, in the draft. Undo brings back what it replaced.`);
      }
      announce(editing ? `Saved the webhook from ${chosen?.name ?? "its endpoint"}` : `Added the webhook from ${chosen?.name ?? "the endpoint"}`);
      onDone(true);
    },
    onError: (e) => setRefused((e instanceof ApiError && REFUSALS[e.code]) || "The webhook couldn't be saved. Try again."),
  });
  const remove = useMutation({
    mutationFn: () => deleteBinding(t.tenantId, binding!.id),
    onSuccess: () => {
      setRemoving(false);
      announce(`Removed the webhook from ${binding?.endpoint.name ?? "its endpoint"}`);
      onDone(true);
    },
    onError: () => {
      setRemoving(false);
      setRefused("The webhook couldn't be removed. Try again.");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!chosen) return setRefused("Choose an endpoint.");
    const f = filter();
    if (f) save.mutate(f);
  }

  const senderOf = (trigger: string | null) => {
    const x = (types.data ?? []).find((y) => y.key === trigger);
    return x ? senderName(x) : trigger ? "an unknown sender" : "another sender";
  };
  return (
    <form
      onSubmit={submit} aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onDone(false);
        }
      }}
      className="flex flex-col gap-4 rounded-lg border border-line-strong p-3"
    >
      <h4 id={`${id}-title`} className="text-body font-semibold">{editing ? `The webhook from ${binding.endpoint.name}` : "New webhook"}</h4>
      {editing ? (
        <p className="text-small"><span className="font-semibold">Endpoint</span> {binding.endpoint.name} · {senderOf(binding.endpoint.trigger)}</p>
      ) : (
        <Select label="Endpoint" value={endpointId ?? ""} onChange={(e) => setEndpointId(e.target.value || null)} autoFocus>
          <option value="">Choose an endpoint</option>
          {choices.map((e) => (
            <option key={e.id} value={e.id} disabled={taken.has(e.id)}>
              {e.name} · {taken.has(e.id) ? "already starts this workflow" : `${senderOf(e.trigger)}${e.enabled ? "" : ", off"}`}
            </option>
          ))}
        </Select>
      )}
      {!editing && endpoints.isError && <p className="text-small text-danger">The endpoints couldn&apos;t be loaded. Try again.</p>}
      {chosen && !ready && !types.isError && <p className="text-small text-muted">Loading what this endpoint sends…</p>}
      {chosen && !ready && types.isError && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" className="text-small text-danger">What this endpoint sends couldn&apos;t be loaded, so its topics can&apos;t be shown.</p>
          <Button size="sm" disabled={types.isFetching} onClick={() => void types.refetch()}>Try again</Button>
        </div>
      )}
      {chosen && ready && byTopic && type && (
        <>
          <Select label="Topic" value={shownTopic ?? ""} onChange={(e) => setTopic(e.target.value)}>
            {topics.map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
          <p className="text-small text-muted">{senderName(type)} sends every topic you subscribe to one URL; this workflow runs for this one.</p>
          {!editing && offerShape && (
            <Check
              label="Use this topic's shape for the input" checked={useShape} disabled={false} onChange={setUseShape}
              hint={fields > 0 ? `Replaces the input's ${fields === 1 ? "field" : `${fields} fields`}, in the draft: Undo brings ${fields === 1 ? "it" : "them"} back.` : "In the draft: Undo brings back what it replaced."}
            />
          )}
        </>
      )}
      {chosen && ready && !byTopic && (
        <fieldset className="flex min-w-0 flex-col gap-2">
          <legend className="mb-1 text-small font-semibold">Runs for events where</legend>
          {type && topics.length > 0 && <p className="text-small text-muted">Its conditions aren&apos;t a topic alone: they&apos;re kept as they are, and change here.</p>}
          {clauses.map((c, i) => (
            <div key={i} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  aria-label={`Field ${i + 1}`} value={c.pointer} placeholder="/type" spellCheck={false} aria-invalid={!!errors[i]}
                  onChange={(e) => setClauses((x) => x.map((y, j) => (j === i ? { ...y, pointer: e.target.value } : y)))}
                  className={`${controlClass(!!errors[i])} w-auto min-w-0 flex-1 basis-32`}
                />
                <span className="text-small">is</span>
                <input
                  aria-label={`Value ${i + 1}`} value={c.value} spellCheck={false} aria-invalid={!!errors[i]}
                  onChange={(e) => setClauses((x) => x.map((y, j) => (j === i ? { ...y, value: e.target.value } : y)))}
                  className={`${controlClass(!!errors[i])} w-auto min-w-0 flex-1 basis-32`}
                />
                <Button size="sm" aria-label={`Remove condition ${i + 1}`} onClick={() => setClauses((x) => x.filter((_, j) => j !== i))}>×</Button>
              </div>
              {errors[i] && <p className="text-small text-danger">{errors[i]}</p>}
            </div>
          ))}
          <Button size="sm" className="self-start" disabled={clauses.length >= MAX_CLAUSES} onClick={() => setClauses((x) => [...x, { pointer: "", value: "" }])}>
            ＋ Condition
          </Button>
          <p className="text-small text-muted">
            All must hold, 8 at most. A field is a pointer into the event, like /type; 1 is a number and true a yes, as written, and &quot;1&quot; in quotes
            is text. No condition: every event.
          </p>
        </fieldset>
      )}
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={save.isPending || !chosen || !ready}>{editing ? "Save" : "Add the webhook"}</Button>
        <Button size="sm" onClick={() => onDone(false)}>Cancel</Button>
        {editing && <Button size="sm" variant="danger-outline" onClick={() => setRemoving(true)}>Remove the webhook…</Button>}
      </div>
      {!editing && (
        <p className="text-small text-muted">
          No endpoint yet?{" "}
          <Link to="/t/$tenantId/settings/webhooks" params={{ tenantId: t.tenantId }} className="text-accent-ink underline">Settings › Webhook endpoints</Link>{" "}
          makes one.
        </p>
      )}
      {editing && (
        <ConfirmDialog
          open={removing} title={`Remove the webhook from ${binding.endpoint.name}?`} confirmLabel="Remove the webhook"
          busy={remove.isPending} onConfirm={() => remove.mutate()} onCancel={() => setRemoving(false)}
        >
          Its events stop starting this workflow at once. The endpoint stays, for its other workflows.
        </ConfirmDialog>
      )}
    </form>
  );  // prettier-ignore
}
