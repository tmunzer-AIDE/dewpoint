// SPDX-License-Identifier: Apache-2.0
// The input from a webhook trigger's topic (4c-3b; the InputMist board): a topic picked from what the plugin declares
// (`/trigger-types`), its shape copied into the draft whole, read only here, and replaceable: another topic, form
// fields, or JSON. Undo brings back what it replaced. Its buttons are where focus comes back to (`data-back`).
import { useId, useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { inputOf, setSettings, shapeRows } from "../../../lib/input";
import { possessive, senderName, type TriggerType } from "../../../lib/triggers";
import { useTriggers } from "./context";

const SHOWN = 8; // topics listed at once: a search finds the rest

export function MistPicker({ type, fields, onDone }: { type: TriggerType; fields: number; onDone: () => void }) {
  const { actions } = useTriggers();
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const legend = useId();
  const found = Object.keys(type.topics).filter((t) => t.includes(query.trim().toLowerCase()));
  const sender = senderName(type);
  const use = () => {
    if (chosen === null) return;
    const shape = type.topics[chosen];
    if (actions.update((d) => setSettings(d, { input_schema: shape }), `The input is now ${possessive(chosen)} shape. Undo brings back what it replaced.`) === null) onDone();
  };
  return (
    <div role="group" aria-labelledby={legend} className="flex flex-col gap-3">
      <span id={legend} className="text-small font-semibold">Use a {sender} event</span>
      <input
        type="search" aria-label="Find a topic" placeholder="Find a topic, like device" value={query} autoFocus
        onChange={(e) => setQuery(e.target.value)} className={controlClass(false)}
      />
      <div role="radiogroup" aria-label="Topic" className="flex flex-col gap-1">
        {found.slice(0, SHOWN).map((t) => (
          <label key={t} className="flex min-h-6 items-center gap-2 font-mono text-small">
            <input type="radio" name="topic" value={t} checked={chosen === t} onChange={() => setChosen(t)} className="size-[16px] accent-accent" />
            {t}
          </label>
        ))}
        {found.length === 0 && <span className="text-small text-muted">No topic has that in its name.</span>}
        {found.length > SHOWN && <span className="text-small text-muted">and {found.length - SHOWN} more topics: find them by name</span>}
      </div>
      <p className="text-small text-muted">
        {fields > 0
          ? `This replaces the input's ${fields === 1 ? "field" : `${fields} fields`} with the event's shape. Undo brings ${fields === 1 ? "it" : "them"} back.`
          : "The input becomes the event's shape. Undo brings back what it replaced."}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" disabled={chosen === null} onClick={use}>{chosen === null ? "Use this topic" : `Use ${chosen}`}</Button>
        <Button size="sm" onClick={onDone}>Cancel</Button>
      </div>
    </div>
  );  // prettier-ignore
}

export function MistShape({ type, topic, onAnother, onJson, onFields }: {
  type: TriggerType; topic: string; onAnother: () => void; onJson: () => void; onFields: () => void;
}) {  // prettier-ignore
  const { doc, editable, actions } = useTriggers();
  const { rows, more } = shapeRows(inputOf(doc), topic);
  const sender = senderName(type);
  const example = rows.find((r) => r.path.startsWith("[ ]."))?.path.slice(4);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-small font-semibold">A {sender} event: <span className="font-mono">{topic}</span></p>
      <ul aria-label="The event's shape" className="flex flex-col rounded-lg border border-line px-3 py-1">
        {rows.map((r) => (
          <li key={r.path} className={`flex flex-wrap gap-x-2 py-1 text-small ${r.path.startsWith("[ ]") ? "pl-4" : ""}`}>
            <span className="font-mono">{r.path}</span>
            <span className="text-muted">{r.what}{r.optional && " · may be missing"}</span>
          </li>
        ))}
        {more && <li className="py-1 pl-4 text-small text-muted">and more fields</li>}
      </ul>
      <p className="text-small text-muted">
        Read only: it&apos;s {possessive(sender)} shape.
        {example && <> A step reads one event as <code className="font-mono">trigger.events[0].{example}</code>; the data tree lists them all.</>}
      </p>
      <div className="flex flex-wrap gap-2">
        {editable && <Button size="sm" data-back="mist" onClick={onAnother}>Use another event…</Button>}
        {editable && (
          <Button
            size="sm"
            onClick={() => {
              const said = "The input is form fields now, none yet. Undo brings the event's shape back.";
              if (actions.update((d) => setSettings(d, { input_schema: { type: "object", properties: {} } }), said) === null) onFields();
            }}
          >
            Use form fields instead
          </Button>
        )}
        <Button size="sm" data-back="json" onClick={onJson}>{editable ? "Edit as JSON" : "Show as JSON"}</Button>
      </div>
    </div>
  );  // prettier-ignore
}
