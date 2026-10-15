// SPDX-License-Identifier: Apache-2.0
// One value a step test sends (4d-1c; the simulation design §7.6; the TestTab and TestOther boards): its title and what
// it is beside it, its pointer, the choices its read allows, its value (a sensitive one typed and masked, never
// prefilled), where it comes from or why it's typed, and what's wrong with it.
import { useId } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { Tag } from "../../../components/Tag";
import type { SeedEntry } from "../../../lib/simulations";
import { choicesOf, hintOf, isText, prefilled, typeWords, type Choice, type SeedInput } from "./seeds";

const SAID: Record<Choice, string> = { value: "A value", null: "Null", absent: "Absent: as if it was never set" };

export function SeedField({ entry: e, title, input, error, isNew, onChange }: {
  entry: SeedEntry; title: string; input: SeedInput; error: string | null; isNew: number | null; onChange: (input: SeedInput) => void;
}) {  // prettier-ignore
  const id = useId();
  const choices = choicesOf(e);
  const sample = prefilled(e);
  const fromSample = sample !== null && input.text === sample;
  // The sample's line only while the value is still the sample's.
  const hint = fromSample ? hintOf(e) : hintOf({ ...e, prefill: { state: "typed", reason: e.prefill.state === "prefilled" ? null : e.prefill.reason, value: null } });
  const described = [hint ? `${id}-hint` : null, error ? `${id}-err` : null].filter(Boolean).join(" ") || undefined;
  const valued = input.choice === "value" || choices.length === 1;
  const change = (text: string) => onChange({ choice: "value", text });
  return (
    <div data-pointer={e.pointer} className="flex flex-col gap-1.5">
      <label id={`${id}-label`} htmlFor={id} className="text-small font-semibold">
        {title} <Tag>{e.required ? "required" : "optional"}</Tag>
        {e.nullable && <> <Tag>nullable</Tag></>}
        {e.sensitive && <> <Tag>sensitive</Tag></>}
        {" "}<Tag>{typeWords(e.types)}</Tag>
        {isNew !== null && <> <Tag>{`new in revision ${isNew}`}</Tag></>}
      </label>
      <code className="font-mono text-meta break-all text-muted">{e.pointer}</code>
      {choices.length > 1 && (
        <div role="radiogroup" aria-labelledby={`${id}-label`} aria-describedby={valued ? undefined : described} className="flex flex-wrap gap-x-4 gap-y-1 text-small">
          {choices.map((c) => (
            <label key={c} className="flex min-h-11 items-center gap-1.5">
              <input type="radio" name={id} checked={input.choice === c} onChange={() => onChange({ ...input, choice: c })} />
              {SAID[c]}
            </label>
          ))}
        </div>
      )}
      {valued &&
        (isText(e) || e.sensitive ? (
          <input
            id={id} type={e.sensitive ? "password" : "text"} autoComplete="off" value={input.text} aria-invalid={!!error} aria-describedby={described}
            className={controlClass(!!error)} onChange={(ev) => change(ev.target.value)}
          />
        ) : (
          <textarea
            id={id} rows={4} spellCheck={false} value={input.text} aria-invalid={!!error} aria-describedby={described}
            className={`${controlClass(!!error)} py-2 font-mono text-small`} onChange={(ev) => change(ev.target.value)}
          />
        ))}
      {(hint || fromSample) && (
        <div className="flex flex-wrap items-center gap-2">
          {hint && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
          {fromSample && <Button size="sm" aria-label={`Clear ${title}`} onClick={() => change("")}>Clear</Button>}
        </div>
      )}
      {error && <p id={`${id}-err`} className="text-small text-danger">{error}</p>}
    </div>
  );
}
