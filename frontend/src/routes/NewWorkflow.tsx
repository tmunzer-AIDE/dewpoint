// SPDX-License-Identifier: Apache-2.0
// "New workflow" (screen 1b; 4b ruling 1; 4c-3b's "What starts it?", the NewWorkflow board): what starts it, then
// Blank or Import from file, then a name. What starts it seeds the draft and opens the new workflow on its Triggers: a
// Mist webhook gives the input its topic's shape and binds the endpoint at once; a CSV file declares one column to
// define; a schedule waits for a first version. An imported file keeps its own input (the owner's ruling), its webhook
// still bound. "Describe it" comes with sub-project 5; "From template" waits for curated templates (D9). A native modal
// dialog (D23): focus moves in and back, Escape closes.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "../components/Button";
import { Field, Select } from "../components/Field";
import { announce } from "../lib/announce";
import { ApiError, client, ok } from "../lib/client";
import { newCsv } from "../lib/csv";
import { asGraph } from "../lib/graph";
import { setSettings } from "../lib/input";
import { createBinding, endpointsQuery, possessive, senderName, triggerTypesQuery } from "../lib/triggers";
import type { WorkflowDetail, WorkflowDocument } from "../lib/workflows";
import { ImportBindings, UNBOUND, useBindingChoices, type Chosen } from "./ImportBindings";

type Start = "blank" | "import";
type Trigger = "hand" | "schedule" | "webhook" | "csv";

// The API's `WorkflowDocument`, `Binding` and `BindingSite` (Task 5), mirrored: a file that passes here passes the
// model there, and the API's own refusals are about the graph and the bindings, not the envelope.
const BINDING_ID = /^[a-z][a-z0-9_]{0,31}$/;
const MAX_BINDINGS = 10_000; // bindings in a file, and sites in a binding

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const keysAre = (v: Record<string, unknown>, keys: string[]) =>
  Object.keys(v).length === keys.length && keys.every((k) => k in v);
const sized = (v: unknown, min: number, max: number) => typeof v === "string" && v.length >= min && v.length <= max;

function isSite(s: unknown): boolean {
  return isObject(s) && keysAre(s, ["node", "field"]) && (s.node === null || sized(s.node, 0, 64)) && sized(s.field, 2, 200);
}

function isBinding(b: unknown): boolean {
  if (!isObject(b) || !keysAre(b, ["id", "kind", "type", "label", "sites"])) return false;
  if (typeof b.id !== "string" || !BINDING_ID.test(b.id) || !sized(b.label, 0, 200)) return false;
  if (!(b.kind === "connection" ? sized(b.type, 1, 100) : b.kind === "workflow" && b.type === null)) return false;
  return Array.isArray(b.sites) && b.sites.length > 0 && b.sites.length <= MAX_BINDINGS && b.sites.every(isSite);
}

/** A workflow file, or null: the whole envelope is checked here, as the API's model checks it; the API then checks
 * the graph and the bindings against its node types (4b ruling 18). */
export function parseDocument(text: string): WorkflowDocument | null {
  let doc: unknown;
  try {
    doc = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isObject(doc) || !keysAre(doc, ["format", "format_version", "name", "graph", "bindings"])) return null;
  if (doc.format !== "dewpoint.workflow" || doc.format_version !== 1 || !sized(doc.name, 0, 100)) return null;
  if (!isObject(doc.graph) || !Array.isArray(doc.bindings) || doc.bindings.length > MAX_BINDINGS) return null;
  if (!doc.bindings.every(isBinding)) return null;
  const ids = doc.bindings.map((b) => (b as { id: string }).id);
  if (new Set(ids).size !== ids.length) return null;
  return doc as unknown as WorkflowDocument;
}

const REASONS: Record<string, string> = {
  unknown: "isn't one of this tenant's",
  wrong_type: "is of another type",
  unexpected: "isn't in the file",
};

// The API's `bad_document` reasons (Task 5), the first one said.
const DOCUMENT: Record<string, string> = {
  unknown_type: "it has steps of a type this server doesn't know",
  duplicate_node: "two of its steps share an id",
  embedded_value: "it holds a connection or workflow id where a binding goes. Export it again from Dewpoint",
  duplicate_binding: "its bindings don't match its steps",
  overlapping_site: "its bindings don't match its steps",
  bad_site: "its bindings don't match its steps",
};

function explain(e: unknown, doc: WorkflowDocument | null): string {
  if (!(e instanceof ApiError)) return "The workflow couldn't be created. Try again.";
  if (e.code === "name_taken") return "A workflow with this name exists. Choose another name.";
  if (e.status === 403) return "You can't create workflows in this tenant.";
  if (e.code === "bad_binding") {
    const body = e.body as { binding?: string; reason?: string };
    const label = doc?.bindings.find((b) => b.id === body.binding)?.label ?? "A binding";
    return `${label} ${REASONS[body.reason ?? ""] ?? "can't be bound"}.`;
  }
  if (e.code === "bad_document") {
    const first = (e.body as { problems?: { reason: string }[] }).problems?.[0]?.reason ?? "";
    return `The file can't be imported: ${DOCUMENT[first] ?? "it doesn't match this server's steps"}.`;
  }
  if (e.code === "invalid") {
    const body = e.body as { diagnostics?: { message: string }[] };
    if (!body.diagnostics) return "That file isn't a Dewpoint workflow this server can read.";
    const first = body.diagnostics[0]?.message;
    return `The file's graph isn't valid${first ? `: ${first}` : ""}.`;
  }
  return "The workflow couldn't be created. Try again.";
}

/** What the import binds: each chosen id; a binding left unbound is left out (the API leaves its sites empty). */
const bound = (chosen: Chosen): Record<string, string> =>
  Object.fromEntries(Object.entries(chosen).filter(([, value]) => value !== UNBOUND));

const CHOICE = "flex cursor-pointer flex-col gap-1 rounded-lg border border-line-strong bg-surface p-4 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:disabled]:cursor-not-allowed";

/** A workflow made, and what of its triggers wasn't: the dialog stays to say so, with the way to open it. */
type Partly = { wf: WorkflowDetail; missed: string };

export function NewWorkflow({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState<Trigger>("hand");
  const [start, setStart] = useState<Start>("blank");
  const [doc, setDoc] = useState<WorkflowDocument | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Chosen>({});
  const [error, setError] = useState<string | null>(null);
  const [partly, setPartly] = useState<Partly | null>(null);
  const choices = useBindingChoices(tenantId, doc?.bindings ?? []);
  const [reading, setReading] = useState(false);
  const selection = useRef(0); // the latest file chosen: an earlier one's read, answering late, changes nothing
  // The webhook trigger plugins declare (Mist's), and this tenant's endpoints made for it.
  const types = useQuery(triggerTypesQuery);
  const endpoints = useQuery(endpointsQuery(tenantId));
  const webhook = (types.data ?? []).find((t) => Object.keys(t.topics).length > 0);
  const senders = (endpoints.data?.endpoints ?? []).filter((e) => webhook && e.trigger === webhook.key);
  const [endpointId, setEndpointId] = useState<string | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const endpoint = senders.find((e) => e.id === endpointId) ?? senders[0] ?? null;
  const topics = webhook ? Object.keys(webhook.topics) : [];
  const shownTopic = topic ?? topics[0] ?? null;
  // Whether this dialog still speaks for the screen. Once it's dismissed, or gone with its tenant's screen, a creation
  // that answers late refreshes that tenant's list but neither opens the workflow nor announces it. Dismissing never
  // cancels the request: the server may still create the workflow (the owner's review of milestone 3).
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("input[name='trigger']:checked")?.focus();
    }
  }, []);

  const open = (wf: WorkflowDetail) =>
    navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: wf.id }, search: { triggers: true } });

  /** The new draft seeded with what starts it: a webhook topic's shape, or a CSV file of one column. An import keeps
   * its own input. */
  async function seed(wf: WorkflowDetail) {
    if (start !== "blank" || (trigger !== "webhook" && trigger !== "csv")) return;
    const draft = asGraph(wf.draft);
    const next = trigger === "csv" ? setSettings(draft, { csv: newCsv() }) : setSettings(draft, { input_schema: webhook!.topics[shownTopic!] });
    await ok(
      client.PUT("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft", {
        params: { path: { tenant_id: tenantId, workflow_id: wf.id }, header: { "If-Match": String(wf.draft_revision) } },
        body: next,
      }),
    );
  }

  const create = useMutation({
    mutationFn: async () => {
      const path = { params: { path: { tenant_id: tenantId } } };
      const wf = start === "blank"
        ? await ok(client.POST("/api/v1/t/{tenant_id}/workflows", { ...path, body: { name: name.trim() } }))
        : await ok(client.POST("/api/v1/t/{tenant_id}/workflows/import", { ...path, body: { name: name.trim(), document: doc!, bind: bound(chosen) } }));  // prettier-ignore
      // Made: what follows can fail without unmaking it, and says so (the dialog stays, with the way to open it).
      try {
        await seed(wf);
      } catch {
        return { wf, missed: trigger === "csv" ? "its CSV file wasn't added" : `its input wasn't given ${possessive(shownTopic ?? "the topic")} shape` };
      }
      if (trigger === "webhook" && endpoint && webhook && shownTopic) {
        try {
          await createBinding(tenantId, endpoint.id, { workflow_id: wf.id, filter: [{ pointer: webhook.topic_pointer, value: shownTopic }] });
        } catch {
          return { wf, missed: `its webhook from ${endpoint.name} wasn't added` };
        }
      }
      return { wf, missed: null };
    },
    onMutate: () => setError(null),
    onSuccess: async ({ wf, missed }) => {
      await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
      if (!live.current) return;
      if (missed) {
        setPartly({ wf, missed });
        announce(`Created ${wf.name}, but ${missed}`);
        return;
      }
      announce(`Created ${wf.name}`);
      dialog.current?.close();
      await open(wf);
    },
    onError: (e) => setError(explain(e, doc)),
  });

  async function readFile(file: File | undefined) {
    const mine = ++selection.current;
    setDoc(null);
    setChosen({});
    setFileError(null);
    setReading(file !== undefined);
    if (!file) return;
    let text: string;
    try {
      text = await file.text();
    } catch {
      if (mine !== selection.current) return;
      setReading(false);
      setFileError("That file couldn't be read. Choose it again, or another.");
      return;
    }
    if (mine !== selection.current) return;
    setReading(false);
    const parsed = parseDocument(text);
    if (!parsed) {
      setFileError("That file isn't a Dewpoint workflow.");
      return;
    }
    setDoc(parsed);
    // The file's name only where the person hasn't typed one meanwhile.
    setName((typed) => (typed.trim() ? typed : parsed.name.slice(0, 100)));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  // An import waits for what its bindings are chosen from, and for a choice for each: unbound is chosen, never the
  // default, nor a lookup that failed (ruling 28). A webhook waits for its endpoint and topic.
  const chosenAll = doc !== null && doc.bindings.every((b) => chosen[b.id] !== undefined);
  const webhookReady = trigger !== "webhook" || (endpoint !== null && shownTopic !== null);
  const ready = name.trim().length > 0 && webhookReady && (start === "blank" || (chosenAll && choices.state === "ready"));
  const sender = webhook ? senderName(webhook) : null;
  const opens =
    trigger === "webhook" && endpoint && shownTopic
      ? start === "blank"
        ? `It opens on its Triggers: the input is ${possessive(shownTopic)} shape, and the webhook is bound to ${endpoint.name}.`
        : `It opens on its Triggers, its webhook bound to ${endpoint.name}; the file's input stays as it is.`
      : trigger === "csv" ? "It opens on its Triggers, with a CSV file of one column to define."
      : trigger === "schedule" ? "It opens on its Triggers: a schedule can be added once a first version is published."
      : "It opens on its Triggers: by hand, its input is the run's form.";  // prettier-ignore

  const radio = (value: Trigger, label: string, hint: string, disabled = false, extra?: ReactNode) => (
    <label className={CHOICE}>
      <span className="flex items-center gap-2">
        <input type="radio" name="trigger" value={value} checked={trigger === value} disabled={disabled} onChange={() => setTrigger(value)} />
        <span className="font-semibold">{label}</span>
      </span>
      <span className="text-small text-muted">{hint}</span>
      {extra}
    </label>
  );  // prettier-ignore

  return (
    <dialog
      ref={dialog}
      aria-labelledby="new-workflow-title"
      onClose={() => {
        live.current = false;
        onClose();
      }}
      className="mx-auto mt-16 w-[640px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <form onSubmit={submit} className="flex flex-col gap-5">
        <h2 id="new-workflow-title" className="text-h3 font-semibold">New workflow</h2>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-small font-semibold">What starts it?</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {radio("hand", "By hand", "Someone starts it, filling in a form.")}
            {radio("schedule", "On a schedule", "Set once a first version is published.")}
            {radio(
              "webhook", sender ? `A ${sender} webhook` : "A webhook",
              senders.length > 0 ? `Runs for each event of a topic ${sender ?? "it"} sends.` : "No endpoint for it yet: Settings › Webhook endpoints makes one.",
              senders.length === 0,
              trigger === "webhook" && senders.length > 0 && (
                <span className="flex flex-col gap-2 pt-1">
                  <Select label="Endpoint" value={endpoint?.id ?? ""} onChange={(e) => setEndpointId(e.target.value)}>
                    {senders.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                  </Select>
                  <Select label="Topic" value={shownTopic ?? ""} onChange={(e) => setTopic(e.target.value)}>
                    {topics.map((t) => <option key={t} value={t}>{t}</option>)}
                  </Select>
                </span>
              ),
            )}
            {radio("csv", "A CSV file", "Someone starts it with a file: one run reads its rows.")}
          </div>
        </fieldset>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-small font-semibold">Then</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className={CHOICE}>
              <span className="flex items-center gap-2">
                <input type="radio" name="start" value="blank" checked={start === "blank"} onChange={() => setStart("blank")} />
                <span className="font-semibold">Blank</span>
              </span>
              <span className="text-small text-muted">
                A start card on the canvas. Add steps from ＋ or press <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">A</kbd>.
              </span>
            </label>
            <label className={CHOICE}>
              <span className="flex items-center gap-2">
                <input type="radio" name="start" value="import" checked={start === "import"} onChange={() => setStart("import")} />
                <span className="font-semibold">Import from file</span>
              </span>
              <span className="text-small text-muted">
                A workflow exported from Dewpoint. Its connections are bound to yours.
                {trigger === "webhook" && " An imported workflow keeps its own input; its Triggers say if the webhook's events don't fit it."}
              </span>
            </label>
          </div>
        </fieldset>
        {start === "import" && (
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-small font-semibold">Workflow file</span>
              <input type="file" accept=".json,application/json" onChange={(e) => void readFile(e.target.files?.[0])} className="text-body" />
            </label>
            {reading && <p role="status" className="text-small text-muted">Reading the file…</p>}
            {fileError && <p role="alert" className="text-small text-danger">{fileError}</p>}
            {doc && <ImportBindings bindings={doc.bindings} choices={choices} chosen={chosen} onChange={setChosen} />}
          </div>
        )}
        <Field label="Name" name="name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <p className="text-small text-muted">{opens}</p>
        {trigger === "webhook" && senders.length === 0 && (
          <p className="text-small">
            <Link to="/t/$tenantId/settings/webhooks" params={{ tenantId }} className="text-accent-ink underline">Settings › Webhook endpoints</Link> makes one.
          </p>
        )}
        {error && <p role="alert" className="text-body text-danger">{error}</p>}
        {partly && (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-body text-danger">
            <span>Created {partly.wf.name}, but {partly.missed}: open it, and add it in its Triggers.</span>
            <Button size="sm" onClick={() => {
              dialog.current?.close();
              void open(partly.wf);
            }}>
              Open {partly.wf.name}
            </Button>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={!ready || create.isPending || partly !== null}>
            {start === "blank" ? "Create and open" : "Import and open"}
          </Button>
        </div>
      </form>
    </dialog>
  );  // prettier-ignore
}
