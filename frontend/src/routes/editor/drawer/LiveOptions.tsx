// SPDX-License-Identifier: Apache-2.0
// A field whose choices the step's type lists (4c-1, ruling 14; plugins-3 D3). The value is typed freely, and its
// choices load only when the person asks, through the step's connection: an options call reaches the plugin's
// service, so it's never a side effect of opening a drawer (D24). Choices belong to their scope (tenant, type, field,
// the connection's id and revision), and each change of scope is a new era: shown choices go, and an answer from an
// older era is ignored, even when the scope comes back. They help; they never gate what's typed.
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { ApiError, client, ok, type Schemas } from "../../../lib/client";
import { valueAt } from "../../../lib/config";
import { idKey, sameId } from "../../../lib/graph";
import { fieldsOf } from "../../../lib/schemaForm";
import { useDrawer } from "./context";
import { connectionsQuery } from "./pickers";
import type { ControlProps } from "./scalars";

type Option = Schemas["OptionOut"];
type Choices =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "done"; options: Option[] }
  | { status: "failed"; why: string };

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
  if (choices.status === "done" && choices.options.length === 0) return "No choices match.";
  return "";
}

export function OptionsControl({ spec, value, literal, id, describedBy, invalid, disabled, onChange }: ControlProps) {
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
  // Each change of scope is a new era, never to be returned to: choices from A, then B, then A again are A's first
  // era's, and stay gone (the review of revision 2). Requests and results carry their era.
  const [seen, setSeen] = useState(scope);
  const [era, setEra] = useState(0);
  if (seen !== scope) {
    setSeen(scope);
    setEra((e) => e + 1);
  }
  const eraNow = useRef(era);
  eraNow.current = era;
  const [choices, setChoices] = useState<{ era: number; state: Choices }>({ era, state: { status: "idle" } });
  const shown: Choices = choices.era === era && seen === scope ? choices.state : { status: "idle" };
  const blocked = takes && chosen === null;
  // Its scope isn't known until the connection's revision is: while the list loads, when it fails, when it doesn't
  // name the connection (the review of revision 2).
  const unsettled = takes && chosen !== null && (revision === null || listed.isError); // a failed refresh keeps old data
  const typed = drawer.held("text", spec.pointer); // what a refused write turned away (ruling 18)
  const text = typed?.text ?? (typeof value === "string" ? value : "");
  async function load() {
    const asked = era;
    setChoices({ era: asked, state: { status: "loading" } });
    try {
      const answer = await ok(
        client.POST("/api/v1/t/{tenant_id}/node-types/{ref}/options", {
          params: { path: { tenant_id: drawer.tenantId, ref: type.ref } },
          body: { field: spec.name, connection_id: chosen, query: text.slice(0, 200) },
        }),
      );
      if (eraNow.current === asked) setChoices({ era: asked, state: { status: "done", options: answer.options } });
    } catch (e) {
      const why = (e instanceof ApiError && WHY[e.code]) || "The choices couldn't load.";
      if (eraNow.current === asked) setChoices({ era: asked, state: { status: "failed", why } });
    }
  }
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 gap-2">
        <input
          id={id} type="text" value={text} disabled={disabled} spellCheck={false}
          aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required && !spec.entry}
          onChange={(e) => {
            const next = e.target.value;
            const why = onChange(next === "" ? undefined : next, true);
            if (why === null) drawer.release("text", spec.pointer);
            // The edit keeps the reading it began with, a literal's or not (the review of revision 4).
            else drawer.hold("text", spec.pointer, { path: spec.path, label: spec.label, text: next, why, literal: typed?.literal ?? literal, entry: spec.entry });
          }}
          className={controlClass(invalid)}
        />
        <Button className="shrink-0" disabled={disabled || blocked || unsettled || shown.status === "loading"} onClick={() => void load()}>
          Show choices
        </Button>
      </div>
      {blocked && <p className="text-small text-muted">Choose the step&apos;s connection first: the choices come from it.</p>}
      {unsettled && !listed.isPending && (
        <p className="text-small text-muted">
          {listed.isError ? "Connections couldn't load, so the choices can't either." : "The step's connection isn't in this tenant's list, so its choices can't load."}
        </p>
      )}
      <p role="status" className={`text-small ${shown.status === "failed" ? "text-danger" : "text-muted"}`}>{said(shown)}</p>
      {shown.status === "done" && shown.options.length > 0 && (
        <select
          aria-label={`Choices for ${spec.label}`} value="" disabled={disabled} className={controlClass(false)}
          onChange={(e) => {
            // A choice writes as typing does: written, the text held before it goes; refused, it's held, with why.
            const choice = e.target.value;
            const why = onChange(choice, false);
            if (why === null) drawer.release("text", spec.pointer);
            else drawer.hold("text", spec.pointer, { path: spec.path, label: spec.label, text: choice, why, literal: typed?.literal ?? literal, entry: spec.entry });
            document.getElementById(id)?.focus();
          }}
        >
          <option value="">{shown.options.length === 1 ? "1 choice" : `${shown.options.length} choices`}</option>
          {shown.options.map((o, i) => (
            <option key={`${i}:${o.value}`} value={o.value}>{o.label === o.value ? o.label : `${o.label} (${o.value})`}</option>
          ))}
        </select>
      )}
    </div>
  );  // prettier-ignore
}
