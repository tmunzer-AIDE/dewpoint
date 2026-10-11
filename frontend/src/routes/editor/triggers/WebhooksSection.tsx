// SPDX-License-Identifier: Apache-2.0
// A workflow's webhooks (4c-3b; the Webhooks and Rules boards; B13): each binding of an endpoint to this workflow, live
// and saved at once, its events running the published version. A webhook trigger's binding names its topic, and is
// compared with the published version's input: when that isn't the topic's shape, its events may be refused, and the
// topic's shape is offered for the draft (the owner's ruling: warned at the binding, in the editor). Another sender's
// events have no known shape: the input must fit them.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { LoadError } from "../../../components/LoadError";
import { Switch } from "../../../components/Switch";
import { announce } from "../../../lib/announce";
import { asGraph } from "../../../lib/graph";
import { inputOf, inputRows, sameSchema, setSettings } from "../../../lib/input";
import { bindingLine, possessive, topicOf, triggerTypesQuery, updateBinding, versionQuery, workflowBindingsQuery, type WorkflowBinding } from "../../../lib/triggers";
import { useTriggers } from "./context";
import { Section } from "./parts";
import { WebhookForm } from "./WebhookForm";

export function WebhooksSection() {
  const t = useTriggers();
  const qc = useQueryClient();
  const bindings = useQuery(workflowBindingsQuery(t.tenantId, t.workflowId));
  const types = useQuery(triggerTypesQuery);
  const active = useQuery({ ...versionQuery(t.tenantId, t.workflowId, t.activeVersionId ?? ""), enabled: t.activeVersionId !== null });
  const [open, setOpen] = useState<string | null>(null); // "new", or the id of the one being edited (a UUID)
  const [error, setError] = useState<string | null>(null);
  const adder = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["workflows", t.tenantId] });
    void qc.invalidateQueries({ queryKey: ["endpoint-bindings", t.tenantId] });
    return qc.invalidateQueries({ queryKey: ["workflow-bindings", t.tenantId, t.workflowId] });
  };
  const toggle = useMutation({
    mutationFn: (b: { id: string; name: string; enabled: boolean }) => updateBinding(t.tenantId, b.id, { enabled: b.enabled }),
    onMutate: () => setError(null),
    onSuccess: (_, b) => announce(`${b.name}: ${b.enabled ? "on: its events start runs" : "off: its events start no runs"}`),
    onError: (_, b) => setError(`${b.name} couldn't be switched ${b.enabled ? "on" : "off"}. Try again.`),
    onSettled: refresh,
  });
  const published = t.activeNumber !== null;
  const list = bindings.data?.bindings ?? [];
  const typeOf = (b: WorkflowBinding) => (types.data ?? []).find((x) => x.key === b.endpoint.trigger);
  const activeInput = active.data ? inputOf(asGraph(active.data.graph)) : null;

  /** What a binding's events meet: nothing before a publish, a known shape the published input may not be, or an
   * unknown one the input must fit. */
  function fit(b: WorkflowBinding) {
    if (!published) return <span className="text-small text-warn-ink">Events are refused until a version is published, and listed as refused in the endpoint&apos;s events.</span>;
    const type = typeOf(b);
    const topic = topicOf(b.filter, type);
    if (!type || !topic) return <span className="text-small text-muted">Its events have no known shape: the input must fit them, or each is refused.</span>;
    const shape = type.topics[topic];
    if (activeInput === null || sameSchema(activeInput, shape)) return null;
    const fields = inputRows(activeInput).length;
    const inDraft = sameSchema(inputOf(t.doc), shape);
    return (
      <div className="flex flex-col gap-1.5">
        <span className="text-small text-warn-ink">
          Version {t.activeNumber}&apos;s input isn&apos;t {possessive(topic)} shape{fields > 0 ? ` (it has ${fields === 1 ? "1 form field" : `${fields} form fields`})` : ""}: events it doesn&apos;t fit are refused.
        </span>
        {inDraft ? (
          <span className="text-small text-muted">In the draft: it applies once published.</span>
        ) : t.editable ? (
          <Button
            size="sm" className="self-start"
            onClick={() => t.actions.update((d) => setSettings(d, { input_schema: shape }), `The input is now ${possessive(topic)} shape, in the draft: it applies once published. Undo brings back what it replaced.`)}
          >
            Use {possessive(topic)} shape for the input
          </Button>
        ) : null}
      </div>
    );  // prettier-ignore
  }

  const close = (saved: boolean) => {
    setOpen(null);
    if (saved) void refresh();
    requestAnimationFrame(() => (adder.current ?? heading.current)?.focus());
  };
  return (
    <Section id="triggers-webhooks" title="Webhooks" heading={heading} note={published ? `Live · events run version ${t.activeNumber}` : "Live"}>
      {error && <p role="alert" className="text-small text-danger">{error}</p>}
      {bindings.isError && <LoadError what="The webhooks" />}
      {bindings.isSuccess && list.length === 0 && open !== "new" && <p className="text-small text-muted">No webhook starts this workflow.</p>}
      <ul className="flex flex-col">
        {list.map((b) => (
          <li key={b.id} className="flex flex-col gap-1.5 border-t border-line py-2.5 first:border-t-0">
            {open === b.id ? (
              <WebhookForm binding={b} onDone={close} />
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 text-body font-medium">{b.endpoint.name}</span>
                  <span className="flex items-center gap-2">
                    {t.manage ? (
                      <>
                        <Switch checked={b.enabled} label={b.endpoint.name} disabled={toggle.isPending} onCheckedChange={(enabled) => toggle.mutate({ id: b.id, name: b.endpoint.name, enabled })} />
                        <Button size="sm" aria-label={`Edit ${b.endpoint.name}`} onClick={() => setOpen(b.id)}>Edit</Button>
                      </>
                    ) : (
                      <span className="text-small">{b.enabled ? "On" : "Off"}</span>
                    )}
                  </span>
                </div>
                <span className="text-small text-muted">{bindingLine(b, types.data)}</span>
                {!b.endpoint.enabled && <span className="text-small text-warn-ink">Its endpoint is off: events sent to it are refused.</span>}
                {fit(b)}
              </>
            )}
          </li>
        ))}
      </ul>
      {open === "new" ? (
        <WebhookForm binding={null} onDone={close} />
      ) : t.manage ? (
        <Button ref={adder} size="sm" className="self-start" onClick={() => setOpen("new")}>＋ Webhook</Button>
      ) : null}
    </Section>
  );  // prettier-ignore
}
