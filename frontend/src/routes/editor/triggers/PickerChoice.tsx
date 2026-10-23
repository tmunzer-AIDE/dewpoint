// SPDX-License-Identifier: Apache-2.0
// A Choice from a connection's own controls (the 4f-3 design §5.7; the Authoring board): Its choices, one of the lists a
// picker can name, in its plugin's words, and Connection, the tenant's connections of the kind that list's step takes,
// in ruling 107's words. The field's editor holds a half choice (a list without its connection) and writes the picker
// once both are chosen. A field's row says what a picker field lists, and from which connection.
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { Button } from "../../../components/Button";
import { Select } from "../../../components/Field";
import { CONNECTION_STATUS, connectionsQuery } from "../../../lib/connections";
import { sameId } from "../../../lib/graph";
import type { InputPicker } from "../../../lib/input";
import { listOf, pickerLists, type PickerList } from "../../../lib/pickerLists";
import { nodeTypesQuery, type Diagnostic } from "../../../lib/workflows";
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

/** Its choices and Connection: `picker` is the field's as written, `held` the list its editor holds without one. Each
 * choice is given as the list (its field and the step it names) and the connection, either null when not chosen. */
export function PickerChoice({ picker, held, disabled, problems, onChoose }: {
  picker: InputPicker | null; held: string | null; disabled: boolean; problems: Diagnostic[];
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
      <Select
        label="Its choices" value={field ?? ""} disabled={disabled} hint={complete ? HOLDS : undefined}
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
      <div data-focus="connection" className="flex flex-col">
        {field === null ? (
          <Select label="Connection" value="" disabled hint={HALF}>
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
            label="Connection" value="" disabled
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
            label="Connection" value={connection ?? ""} disabled={disabled} hint={complete ? undefined : HALF} error={error}
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
    </>
  );  // prettier-ignore
}
