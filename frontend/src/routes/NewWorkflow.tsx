// SPDX-License-Identifier: Apache-2.0
// "New workflow" (screen 1b; 4b ruling 1): a name, then Blank or Import from file. The trigger step ("What starts
// it?") comes with 4c's trigger setup, "Describe it" with sub-project 5; "From template" waits for curated templates
// (D9). A native modal dialog (D23): focus moves in and back, Escape closes.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { announce } from "../lib/announce";
import { ApiError, client, ok } from "../lib/client";
import type { WorkflowDocument } from "../lib/workflows";
import { ImportBindings, UNBOUND, useBindingChoices, type Chosen } from "./ImportBindings";

type Start = "blank" | "import";

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

const CHOICE = "flex cursor-pointer flex-col gap-1 rounded-lg border border-line-strong bg-surface p-4 has-[:checked]:border-accent has-[:checked]:bg-accent-soft";

export function NewWorkflow({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [start, setStart] = useState<Start>("blank");
  const [doc, setDoc] = useState<WorkflowDocument | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Chosen>({});
  const [error, setError] = useState<string | null>(null);
  const choices = useBindingChoices(tenantId, doc?.bindings ?? []);

  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("input[name='name']")?.focus();
    }
  }, []);

  const create = useMutation({
    mutationFn: () => {
      const path = { params: { path: { tenant_id: tenantId } } };
      return start === "blank"
        ? ok(client.POST("/api/v1/t/{tenant_id}/workflows", { ...path, body: { name: name.trim() } }))
        : ok(client.POST("/api/v1/t/{tenant_id}/workflows/import", { ...path, body: { name: name.trim(), document: doc!, bind: bound(chosen) } }));
    },
    onMutate: () => setError(null),
    onSuccess: async (wf) => {
      announce(`Created ${wf.name}`);
      await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
      dialog.current?.close();
      await navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: wf.id } });
    },
    onError: (e) => setError(explain(e, doc)),
  });

  async function readFile(file: File | undefined) {
    setDoc(null);
    setChosen({});
    setFileError(null);
    if (!file) return;
    const parsed = parseDocument(await file.text());
    if (!parsed) {
      setFileError("That file isn't a Dewpoint workflow.");
      return;
    }
    setDoc(parsed);
    if (!name.trim()) setName(parsed.name.slice(0, 100));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  // An import waits for what its bindings are chosen from, and for a choice for each: unbound is chosen, never the
  // default, nor a lookup that failed (ruling 28).
  const chosenAll = doc !== null && doc.bindings.every((b) => chosen[b.id] !== undefined);
  const ready = name.trim().length > 0 && (start === "blank" || (chosenAll && choices.state === "ready"));

  return (
    <dialog
      ref={dialog}
      aria-labelledby="new-workflow-title"
      onClose={onClose}
      className="mx-auto mt-16 w-[640px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <form onSubmit={submit} className="flex flex-col gap-5">
        <h2 id="new-workflow-title" className="text-h3 font-semibold">New workflow</h2>
        <Field label="Name" name="name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-small font-semibold">How do you want to start?</legend>
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
              <span className="text-small text-muted">A workflow exported from Dewpoint. Its connections are bound to yours.</span>
            </label>
          </div>
        </fieldset>
        {start === "import" && (
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-small font-semibold">Workflow file</span>
              <input type="file" accept=".json,application/json" onChange={(e) => void readFile(e.target.files?.[0])} className="text-body" />
            </label>
            {fileError && <p className="text-small text-danger">{fileError}</p>}
            {doc && <ImportBindings bindings={doc.bindings} choices={choices} chosen={chosen} onChange={setChosen} />}
          </div>
        )}
        {error && <p role="alert" className="text-body text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={!ready || create.isPending}>
            {start === "blank" ? "Create and open" : "Import and open"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
