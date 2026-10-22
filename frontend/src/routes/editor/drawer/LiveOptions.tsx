// SPDX-License-Identifier: Apache-2.0
// A field whose choices the step's type lists (4c-1, ruling 14; plugins-3 D3). The value is typed freely, and its
// choices load only when the person asks, through the step's connection: an options call reaches the plugin's
// service, so it's never a side effect of opening a drawer (D24). Choices belong to their scope (tenant, type, field,
// the connection's id and revision), and each change of scope is a new era: shown choices go, and an answer from an
// older era is ignored, even when the scope comes back. They help; they never gate what's typed. They show as a list
// under the field (4f-2, the Mist step design §5.2; ruling 126: in the drawer's flow); a pick replaces the value and is
// named until the drawer closes or the value changes: the config keeps only the value. The list and its eras are the
// start forms' too (../choices); the words and the route are the drawer's.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { ApiError, client, ok } from "../../../lib/client";
import { connectionsQuery } from "../../../lib/connections";
import { valueAt } from "../../../lib/config";
import { idKey, sameId } from "../../../lib/graph";
import { fieldsOf, type FieldSpec } from "../../../lib/schemaForm";
import { ChoiceList, useScopedChoices, type Choices, type Option } from "../choices";
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

/** Why the choices didn't load, by the API's code (`POST …/node-types/{ref}/options`). */
const WHY: Record<string, string> = {
  connection_unavailable: "The step's connection can't be used: choose another.",
  connection_changed: "The connection changed while the choices loaded. Try again.",
  forbidden: "Your role can't use this connection.",
  plugin_call_timeout: "The choices took too long to load. Try again.",
  plugin_calls_busy: "Too many requests right now. Try again in a moment.",
  too_many_plugin_calls: "Too many requests right now. Try again in a moment.",
  invalid_result: "The service answered with something that isn't a list of choices.",
  plugin_failed: "The service couldn't list the choices.",
  not_an_options_field: "This field has no choices to list.",
  unknown_node_type: "This step's type isn't on this server.",
  tenant_erasing: "This tenant is being erased.",
};

function said(choices: Choices): string {
  if (choices.status === "loading") return "Loading choices…";
  if (choices.status === "failed") return choices.why;
  if (choices.status === "done") return choices.options.length === 0 ? "No choices match." : choices.options.length === 1 ? "1 choice" : `${choices.options.length} choices`;
  return "";
}

/** A field's choices, loaded on request through the step's connection (ruling 109), each answer for its era only. */
function useChoices(spec: FieldSpec) {
  const drawer = useDrawer();
  const type = spec.type;
  const takes = type.credentials.length > 0;
  const field = fieldsOf(type).find((f) => f.widget === "connection");
  const connection = field ? valueAt(drawer.node.config ?? {}, field.path) : undefined;
  const chosen = typeof connection === "string" ? connection : null;
  // The connection's revision: a connection changed elsewhere is another scope. Read from the tenant's list, which
  // the connection picker loads too: a local read, never the service.
  const listed = useQuery({ ...connectionsQuery(drawer.tenantId), enabled: takes && chosen !== null });
  const revision = chosen === null ? null : (listed.data?.find((c) => sameId(c.id, chosen))?.revision ?? null);
  const scope = JSON.stringify([drawer.tenantId, type.ref, spec.name, chosen === null ? null : idKey(chosen), revision]);
  const blocked = takes && chosen === null;
  // Its scope isn't known until the connection's revision is: while the list loads, when it fails, when it doesn't
  // name the connection (the review of revision 2).
  const unsettled = takes && chosen !== null && (revision === null || listed.isError); // a failed refresh keeps old data
  const read = async (query: string) =>
    (
      await ok(
        client.POST("/api/v1/t/{tenant_id}/node-types/{ref}/options", {
          params: { path: { tenant_id: drawer.tenantId, ref: type.ref } },
          body: { field: spec.name, connection_id: chosen, query },
        }),
      )
    ).options;
  const { shown, load, close } = useScopedChoices(scope, read, (e) => (e instanceof ApiError && WHY[e.code]) || "The choices couldn't load.");
  return { shown, load, close, blocked, unsettled, listed };
}

type Choosing = ReturnType<typeof useChoices>;

/** Why the choices can't load yet, and what loading said. */
function ChoiceWords({ choosing }: { choosing: Choosing }) {
  const { shown, blocked, unsettled, listed } = choosing;
  return (
    <>
      {blocked && <p className="text-small text-muted">Choose the step&apos;s connection first: the choices come from it.</p>}
      {unsettled && !listed.isPending && (
        <p className="text-small text-muted">
          {listed.isError ? "Connections couldn't load, so the choices can't either." : "The step's connection isn't in this tenant's list, so its choices can't load."}
        </p>
      )}
      <p role="status" className={`text-small ${shown.status === "failed" ? "text-danger" : "text-muted"}`}>{said(shown)}</p>
    </>
  );  // prettier-ignore
}

/** A pick, named while the field still holds it: the config keeps only its value. */
function usePicked(current: unknown) {
  const [picked, setPicked] = useState<Option | null>(null);
  const note = picked !== null && current === picked.value ? `${picked.label}, picked from the choices.` : null;
  return { note, setPicked };
}

/** Under a field that takes values from earlier steps (4f-2: ruling 127 amended): Show choices, what's said of them,
 * their list, and the pick's name. The query is the field's written text when it holds no value from a step. */
export function ChoicesBelow({ spec, query, current, disabled, onPick, onDone }: {
  spec: FieldSpec; query: string; current: unknown; disabled: boolean; onPick: (value: string) => string | null; onDone: () => void;
}) {  // prettier-ignore
  const choosing = useChoices(spec);
  const { shown, blocked, unsettled } = choosing;
  const { note, setPicked } = usePicked(current);
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div>
        <Button
          size="sm" aria-label={`Show choices: ${spec.label}`} className="max-sm:min-h-[44px]"
          disabled={disabled || blocked || unsettled || shown.status === "loading"} onClick={() => void choosing.load(query)}
        >
          Show choices
        </Button>
      </div>
      <ChoiceWords choosing={choosing} />
      {shown.status === "done" && shown.options.length > 0 && !disabled && (
        <ChoiceList
          label={spec.label} options={shown.options}
          onClose={() => {
            choosing.close();
            onDone();
          }}
          onPick={(o) => {
            if (onPick(o.value) === null) setPicked(o);
            choosing.close();
            onDone();
          }}
        />
      )}
      {note && <p className="text-small">{note}</p>}
    </div>
  );  // prettier-ignore
}

export function OptionsControl({ spec, value, literal, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const drawer = useDrawer();
  const choosing = useChoices(spec);
  const { shown, blocked, unsettled } = choosing;
  const { note, setPicked } = usePicked(value);
  const typed = drawer.held("text", spec.pointer); // what a refused write turned away (ruling 18)
  const text = typed?.text ?? (typeof value === "string" ? value : "");
  const write = (next: string, typing: boolean): string | null => {
    const why = onChange(next === "" ? undefined : next, typing);
    if (why === null) drawer.release("text", spec.pointer);
    // The edit keeps the reading it began with, a literal's or not (the review of revision 4).
    else drawer.hold("text", spec.pointer, { path: spec.path, label: spec.label, text: next, why, literal: typed?.literal ?? literal, entry: spec.entry });
    return why;
  };
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 gap-2">
        <input
          id={id} type="text" value={text} disabled={disabled} spellCheck={false}
          aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
          onChange={(e) => void write(e.target.value, true)}
          className={controlClass(invalid)}
        />
        {/* Named by its field, its visible text first (WCAG 2.5.3): a list of buttons tells them apart (#73). */}
        <Button
          className="shrink-0" aria-label={`Show choices: ${spec.label}`}
          disabled={disabled || blocked || unsettled || shown.status === "loading"} onClick={() => void choosing.load(text)}
        >
          Show choices
        </Button>
      </div>
      <ChoiceWords choosing={choosing} />
      {shown.status === "done" && shown.options.length > 0 && !disabled && (
        <ChoiceList
          label={spec.label} options={shown.options}
          onClose={() => {
            choosing.close();
            document.getElementById(id)?.focus();
          }}
          onPick={(o) => {
            // A choice writes as typing does: written, the text held before it goes; refused, it's held, with why.
            if (write(o.value, false) === null) setPicked(o);
            choosing.close();
            document.getElementById(id)?.focus();
          }}
        />
      )}
      {note && <p className="text-small">{note}</p>}
    </div>
  );  // prettier-ignore
}
