// SPDX-License-Identifier: Apache-2.0
// A Choice from a connection's own controls (the 4f-3 design §5.7; the Authoring board): Its choices, one of the lists a
// picker can name, in its plugin's words, and Connection, the tenant's connections of the kind that list's step takes,
// in ruling 107's words. The field's editor holds a half choice (a list without its connection) and writes the picker
// once both are chosen; then Show choices tries the list as the form will show it. A field's row says what a picker
// field lists, and from which connection. Below 640 px every control here is 44 px (§5.10).
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useMemo } from "react";
import { Button } from "../../../components/Button";
import { Select } from "../../../components/Field";
import { CONNECTION_STATUS, connectionsQuery } from "../../../lib/connections";
import { idKey, sameId } from "../../../lib/graph";
import type { InputPicker } from "../../../lib/input";
import { listOf, pickerLists, type PickerList } from "../../../lib/pickerLists";
import { nodeTypesQuery, type Diagnostic } from "../../../lib/workflows";
import { ChoiceList, useScopedChoices } from "../choices";
import { failedWords, labelWord, nodeChoices, statusWords } from "../pickerField";
import { useTriggers } from "./context";

export const HALF = "Until a list and a connection are chosen, the field is saved as plain text.";
const HOLDS = "The list the form shows; the field holds the picked one's ID.";

/** The lists a picker can name, from the node types the editor holds (a cache hit: it waits for them, R10 §5.3); none
 * while not `enabled`. */
export function usePickerLists(enabled = true): PickerList[] {
  const types = useQuery({ ...nodeTypesQuery, enabled });
  return useMemo(() => (enabled && types.data ? pickerLists(types.data) : []), [enabled, types.data]);
}

/** What a picker field lists, as its row says it: "a choice of Acme Prod's sites". */
export function choiceWords(picker: InputPicker, lists: PickerList[], connections: { id: string; name: string }[]): string {
  const held = picker.connection === null ? undefined : connections.find((c) => sameId(c.id, picker.connection!));
  return `a choice of ${held?.name ?? "the connection"}'s ${listOf(lists, picker.field)?.noun ?? "choices"}`;
}

/** Show choices in the editor (§5.7): the list tried as the form will show it, through its step and its connection,
 * before it's used; picking a choice changes nothing. */
function Try({ picker, label }: { picker: { node: string; field: string; connection: string }; label: string }) {
  const t = useTriggers();
  const id = useId();
  const lists = usePickerLists();
  const listed = useQuery(connectionsQuery(t.tenantId));
  const held = listed.data?.find((c) => sameId(c.id, picker.connection));
  const words = { c: held?.name ?? "the connection", C: held?.name ?? "The connection", n: listOf(lists, picker.field)?.noun ?? "choices", label: labelWord(label) };
  const scope = JSON.stringify([t.tenantId, picker.node, picker.field, idKey(picker.connection), held?.revision ?? null]);
  const { shown, load, close } = useScopedChoices(scope, (query) => nodeChoices(t.tenantId, picker, query), (e) => failedWords(e, words, true));
  const back = () => {
    close();
    document.getElementById(`${id}-show`)?.focus();
  };
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button
          id={`${id}-show`} size="sm" aria-label={`Show choices: ${label}`} className="max-sm:min-h-[44px]" disabled={shown.status === "loading"}
          onClick={() => void load("")}
        >
          Show choices
        </Button>
        <p role="status" className={`min-w-0 text-small ${shown.status === "failed" ? "text-danger" : "text-muted"}`}>
          {shown.status === "idle" ? "Try the list as the form will show it." : statusWords(shown, null, words)}
        </p>
      </div>
      {shown.status === "done" && shown.options.length > 0 && <ChoiceList label={label} options={shown.options} tall onPick={back} onClose={back} />}
    </div>
  );  // prettier-ignore
}

/** Its choices and Connection: `picker` is the field's as written, `held` the list its editor holds without one. Each
 * choice is given as the list (its field and the step it names) and the connection, either null when not chosen. */
export function PickerChoice({ picker, held, label, disabled, problems, onChoose }: {
  picker: InputPicker | null; held: string | null; label: string; disabled: boolean; problems: Diagnostic[];
  onChoose: (list: { field: string; node: string } | null, connection: string | null) => void;
}) {  // prettier-ignore
  const t = useTriggers();
  const lists = usePickerLists();
  const field = picker?.field ?? held;
  const connection = picker?.connection ?? null;
  const entry = field === null ? undefined : listOf(lists, field);
  const listed = useQuery({ ...connectionsQuery(t.tenantId), enabled: field !== null });
  const nodeOf = (f: string) => listOf(lists, f)?.node ?? (picker?.field === f ? picker.node : null);
  const typeOf = (id: string) => listed.data?.find((c) => sameId(c.id, id))?.type;
  const complete = picker !== null && connection !== null;
  const mine = (listed.data ?? []).filter((c) => entry?.credentials.includes(c.type));
  const known = connection !== null && mine.some((c) => sameId(c.id, connection));
  const plugin = entry?.plugin ?? "such";
  const error = problems.length > 0 ? problems.map((d) => d.message).join(" ") : undefined;
  return (
    <>
      <div data-focus="list" className="flex flex-col">
        <Select
          label="Its choices" value={field ?? ""} disabled={disabled} hint={complete ? HOLDS : undefined} tall
          onChange={(e) => {
            const to = e.target.value;
            const node = to === "" ? null : nodeOf(to);
            const kind = connection === null ? undefined : typeOf(connection);
            const keep = connection !== null && to !== "" && (kind === undefined || (listOf(lists, to)?.credentials.includes(kind) ?? true));
            onChoose(node === null ? null : { field: to, node }, keep ? connection : null);
          }}
        >
          <option value="">Choose a list</option>
          {field !== null && entry === undefined && <option value={field}>A list this server doesn&apos;t offer</option>}
          {lists.map((l) => <option key={l.field} value={l.field}>{l.label}</option>)}
        </Select>
      </div>
      <div data-focus="connection" className="flex flex-col">
        {field === null ? (
          <Select label="Connection" value="" disabled hint={HALF} tall>
            <option value="">Choose the list first</option>
          </Select>
        ) : listed.isPending ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-small font-semibold">Connection</span>
            <output data-loading className="text-small text-muted">Loading connections…</output>
          </div>
        ) : listed.isError ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-small font-semibold">Connection</span>
            <output className="flex flex-wrap items-center gap-2 text-small text-danger">
              Connections couldn&apos;t load.
              <Button size="sm" onClick={() => void listed.refetch()}>Try again</Button>
            </output>
          </div>
        ) : mine.length === 0 && connection === null ? (
          <Select
            label="Connection" value="" disabled tall
            hint={
              <>
                {`No ${plugin} connection yet: `}
                <Link to="/t/$tenantId/connections" params={{ tenantId: t.tenantId }} className="underline">add one on Connections</Link>
                , then choose it here.
              </>
            }
          >
            <option value="">{`No ${plugin} connection`}</option>
          </Select>
        ) : (
          <Select
            label="Connection" value={connection ?? ""} disabled={disabled} hint={complete ? undefined : HALF} error={error} tall
            onChange={(e) => onChoose(field === null || nodeOf(field) === null ? null : { field, node: nodeOf(field)! }, e.target.value === "" ? null : e.target.value)}
          >
            <option value="">Choose a connection</option>
            {connection !== null && !known && <option value={connection}>A connection that isn&apos;t in this tenant</option>}
            {mine.map((c) => (
              // The id as the picker writes it, whatever its spelling, so the picker's own stays chosen.
              <option key={c.id} value={known && sameId(c.id, connection) ? connection : c.id}>
                {c.name} · {CONNECTION_STATUS[c.status]}
              </option>
            ))}
          </Select>
        )}
      </div>
      {complete && <Try picker={{ node: picker.node, field: picker.field, connection }} label={label} />}
    </>
  );  // prettier-ignore
}
