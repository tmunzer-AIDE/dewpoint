// SPDX-License-Identifier: Apache-2.0
// A start form's picker field (the 4f-3 design §5.2-§5.5; the Main, States and MoreStates boards): plugins-3 D19's
// `x-dewpoint-picker` as the run form, a re-run, a CSV run's fields, a schedule's form and Simulate show it. The text
// box is the value and the search at once; Show choices (or Enter) lists through the form's route, the list under the
// field (../choices, without taking focus: Down enters it); a pick writes the id and is named on the status line until
// the value is typed over. The list helps, it never gates what's typed (ruling 109). Each form keeps its picks, by
// field, and sends the names of those its input still holds.
import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button } from "../../components/Button";
import { Field } from "../../components/Field";
import { ApiError, client, ok, type Schemas } from "../../lib/client";
import { connectionsQuery } from "../../lib/connections";
import { idKey, sameId } from "../../lib/graph";
import type { StartField } from "../../lib/triggers";
import { ChoiceList, useScopedChoices, type Choices, type Option } from "./choices";

export type Picker = Schemas["PickerOut"];
/** A pick a form made, or a re-run's from its first run (`first`): the choice's label and the value it was picked for. */
export type Pick = { value: string; label: string; first?: boolean };
export type Picks = ReadonlyMap<string, Pick>;

/** What a start form gives its picker fields. */
export type PickerForm = {
  tenantId: string;
  /** What its choices belong to besides the field (ruling 109): the workflow and the version the form shows, or the draft. */
  scope: string;
  /** Lists a field's choices through the form's route (§5.3). */
  read: (f: StartField, picker: Picker, query: string) => Promise<Option[]>;
  /** Simulate's: the draft's picker, through its node's route; the connection's revision is part of the scope. */
  draft: boolean;
  /** A simulated start, or Simulate: listing still reads the connection, and says so under the list. */
  simulated: boolean;
  picks: Picks;
  onPick: (field: string, pick: Pick | null) => void;
};

const PickerContext = createContext<PickerForm | null>(null);
export const PickerProvider = PickerContext.Provider;
export const usePickerForm = () => useContext(PickerContext);

/** One rule for the forms and authoring (§5.2): a string with a complete picker, and no values, default or sensitivity
 * beside it (a sensitive value's name is never shown). `format` isn't in the form: authoring reads it (4f-3c). */
export const isPicker = (f: StartField): f is StartField & { picker: Picker } =>
  f.type === "string" && !!f.picker && f.enum == null && !f.enum_masked && f.default === undefined && !f.default_masked && !f.sensitive;

/** A form's picks, by field: set by a pick, dropped by typing over it or by a re-read of another version (§5.5).
 * `first`: a re-run's, from its first run, until a pick or a drop. */
export function usePicks(first?: Picks) {
  const [picks, setPicks] = useState<Picks | null>(null);
  const shown = picks ?? first ?? NO_PICKS;
  const onPick = (field: string, pick: Pick | null) =>
    setPicks((held) => {
      const next = new Map(held ?? first ?? NO_PICKS);
      if (pick) next.set(field, pick);
      else next.delete(field);
      return next;
    });
  return { picks: shown, onPick, clear: () => setPicks(new Map()) };
}
const NO_PICKS: Picks = new Map();

/** The names a start sends (§5.5): each pick whose value the input holds at its field, else none. Never in the key. */
export function namesFor(picks: Picks, input: Record<string, unknown>): Record<string, { value: string; label: string }> | undefined {
  const held = [...picks].filter(([field, p]) => Object.hasOwn(input, field) && input[field] === p.value);
  return held.length > 0 ? Object.fromEntries(held.map(([field, p]) => [field, { value: p.value, label: p.label }])) : undefined;
}

/** A published version's choices (§5.3: the run form, a CSV run's fields, a re-run, a schedule's form): listed only
 * while that version is the active one (409 `version_changed` once another is, §4.2). */
export const versionChoices =
  (tenantId: string, workflowId: string, versionId: string) =>
  async (f: StartField, _picker: Picker, query: string): Promise<Option[]> =>
    (
      await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/input-options", {
          params: { path: { tenant_id: tenantId, workflow_id: workflowId } },
          body: { field: f.name, query, expected_version_id: versionId },
        }),
      )
    ).options;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** A draft's choices (§5.3: Simulate): through the node type its picker names, with its connection. A connection that
 * isn't a UUID is none of this tenant's: refused here, nothing asked. */
export const draftChoices =
  (tenantId: string) =>
  async (_f: StartField, picker: Picker, query: string): Promise<Option[]> => {
    const connection = idKey(picker.connection);
    if (!UUID.test(connection)) throw new ApiError(422, "connection_unavailable", null);
    return (
      await ok(
        client.POST("/api/v1/t/{tenant_id}/node-types/{ref}/options", {
          params: { path: { tenant_id: tenantId, ref: picker.node } },
          body: { field: picker.field, connection_id: connection, query },
        }),
      )
    ).options;
  };

/** The field's label as the words call it: without "ID", its first word lower-cased unless it's an acronym. */
export function labelWord(label: string): string {
  const bare = label.replace(/\s+ID$/, "");
  return /^\p{Lu}\p{Ll}/u.test(bare) ? `${bare[0]!.toLowerCase()}${bare.slice(1)}` : bare;
}

/** `c`: the connection's name ("the connection" when the tenant's list doesn't hold it), `C` at a sentence's start;
 * `n`: the list's noun ("choices" when unknown); `label`: the field's, as labelWord says it. */
type Words = { c: string; C: string; n: string; label: string };

/** The status line (§5.4): what a listing found, or the pick, or how to list. */
export function statusWords(shown: Choices, picked: Pick | null, { c, C, n, label }: Words): string {
  switch (shown.status) {
    case "loading":
      return `Reading ${c}'s ${n}…`;
    case "failed":
      return shown.why;
    case "done": {
      const { options, query } = shown;
      const typed = query.trim() !== "";
      if (options.length >= 1000) return `The first 1,000 of ${c}'s ${n}: type part of a name to narrow them.`;
      if (options.length === 0) return typed ? `None of ${c}'s ${n} has “${query}” in its name. Type less, or type the ${label}'s ID.` : `${C} has no ${n}: type the ${label}'s ID.`;
      if (!typed) return `${options.length} of ${c}'s ${n}.`;
      return options.length === 1 ? `1 of ${c}'s ${n} has “${query}” in its name.` : `${options.length} of ${c}'s ${n} have “${query}” in their name.`;
    }
    case "idle":
      if (picked) return picked.first ? `${picked.label}, as picked for the first run.` : `${picked.label}, picked from ${c}'s ${n}.`;
      return `One of ${c}'s ${n}: type part of its name, then Show choices.`;
  }
}

/** Why a listing failed, by the API's answer (§5.4); `draft`: Simulate's, through the node's route. */
export function failedWords(e: unknown, { C, n, label }: Words, draft: boolean): string {
  const code = e instanceof ApiError ? e.code : "network";
  const body = (e instanceof ApiError ? (e.body ?? {}) : {}) as { active_version_number?: unknown };
  if (code === "version_changed" && typeof body.active_version_number === "number")
    return `Version ${body.active_version_number} was published after this form opened, and its choices may differ: close the form and start again.`;
  if (code === "workflow_disabled") return `The workflow is disabled, so its choices can't be listed: type the ${label}'s ID, or enable it first.`;
  if (code === "unknown_node_type") return `This list isn't offered any more: type the ${label}'s ID. An editor can choose another list in Triggers.`;
  if (code === "connection_unavailable")
    return draft
      ? `The draft names a connection this tenant doesn't have: choose one in Triggers › Input, or type the ${label}'s ID.`
      : `${C} can't list choices now: an editor can check it on Connections. Type the ${label}'s ID meanwhile.`;
  if (code === "plugin_calls_busy" || (e instanceof ApiError && e.status === 429)) return "Too many lists are being read right now: try again in a moment.";
  if (code === "connection_changed") return `${C} changed while its ${n} were read: Show choices again.`;
  if (code === "not_published" || code === "not_a_picker") return `This field's choices can't be listed: type the ${label}'s ID.`;
  return `${C}'s ${n} couldn't be read: Mist answered with an error. Try again, or type the ${label}'s ID.`;
}

/** A picker field (§5.2, §5.10): a combobox owning its list, its status line describing it. */
export function PickerField({ f, picker, value, error, label, hint, tall, onChange }: {
  f: StartField; picker: Picker; value: string | undefined; error?: string; label: ReactNode; hint?: ReactNode; tall?: boolean; onChange: (v: string) => void;
}) {  // prettier-ignore
  const form = usePickerForm()!;
  const id = useId();
  const connections = useQuery(connectionsQuery(form.tenantId)); // every role reads it (R7 §6)
  const held = connections.data?.find((c) => sameId(c.id, picker.connection));
  const name = f.title ?? f.name;
  const words: Words = { c: held?.name ?? "the connection", C: held?.name ?? "The connection", n: picker.list?.noun ?? "choices", label: labelWord(name) };
  // A draft's choices are its picker's too: the node, the field, the connection and the connection's revision.
  const scope = JSON.stringify([form.scope, f.name, form.draft ? [picker.node, picker.field, idKey(picker.connection), held?.revision ?? null] : null]);
  const { shown, load, close } = useScopedChoices(scope, (query) => form.read(f, picker, query), (e) => failedWords(e, words, form.draft));
  const text = value ?? "";
  const pick = form.picks.get(f.name);
  const named = pick !== undefined && pick.value === text ? pick : null;
  const open = shown.status === "done" && shown.options.length > 0;
  const list = `${id}-list`;
  const back = () => document.getElementById(id)?.focus();
  /** Down enters the shown list; Escape closes it, or drops a listing on its way, never the form or its dialog: from
   * the field or Show choices (4f-3b's final review). */
  const listKeys = (e: KeyboardEvent) => {
    const escape = e.key === "Escape" && (open || shown.status === "loading");
    if (!escape && !(e.key === "ArrowDown" && open)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === "ArrowDown") document.getElementById(list)?.focus();
    else {
      close();
      back();
    }
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Enter") return listKeys(e);
    e.preventDefault(); // lists, never submits the form
    if (shown.status !== "loading") void load(text);
  };
  return (
    <Field
      id={id} label={label} hint={hint} error={error} tall={tall} type="text" autoComplete="off" spellCheck={false} value={text}
      role="combobox" aria-expanded={open} aria-controls={open ? list : undefined} describedBy={`${id}-status`} onKeyDown={onKeyDown}
      onChange={(e) => {
        if (pick) form.onPick(f.name, null); // typed over: its name goes (the owner's call, round 2)
        onChange(e.target.value);
      }}
      below={
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {/* Named by its field, its visible text first (WCAG 2.5.3). */}
            <Button
              size="sm" aria-label={`Show choices: ${name}`} className="max-sm:min-h-[44px]" disabled={shown.status === "loading"}
              onClick={() => void load(text)} onKeyDown={listKeys}
            >
              Show choices
            </Button>
            <p id={`${id}-status`} role="status" className={`min-w-0 text-small ${shown.status === "failed" ? "text-danger" : "text-muted"}`}>
              {statusWords(shown, named, words)}
            </p>
          </div>
          {open && (
            <ChoiceList
              id={list} label={name} options={shown.options} focusOnShow={false} tall
              onClose={() => {
                close();
                back();
              }}
              onPick={(o) => {
                onChange(o.value);
                form.onPick(f.name, { value: o.value, label: o.label });
                close();
                back();
              }}
            />
          )}
          {open && form.simulated && <p className="text-small text-muted">{`Read from ${words.c} now: listing changes nothing in Mist.`}</p>}
        </div>
      }
    />
  );  // prettier-ignore
}
