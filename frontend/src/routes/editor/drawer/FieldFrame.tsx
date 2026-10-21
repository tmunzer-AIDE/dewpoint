// SPDX-License-Identifier: Apache-2.0
// A field's frame (4c-1): its label and the actions on it, then its control (given its id and the ids that describe
// it), its hint, a type hint from the browser (D19) and the server's problems at it, each described by the control
// (WCAG 1.3.1, 3.3.1), and a warning, which never blocks (the message composer's, 4f-1). "(required)" sits beside the label, outside it: the control says it (aria-required). A group, a
// list or a map is a fieldset its legend names, its parts indented, never marked with a left rule (outline §6).
import { useId, type ReactNode } from "react";
import type { Diagnostic } from "../../../lib/workflows";

export interface Described {
  id: string;
  describedBy: string | undefined;
  invalid: boolean;
}

interface Frame {
  label: string;
  required: boolean; // said below the top level: Setup says it once for its own fields
  hint: string | null;
  warn?: string | null; // what the target would cut: said, never blocking
  local: string | null; // what the browser found: the control's text isn't saved
  problems: Diagnostic[];
  actions?: ReactNode;
}

const describing = (id: string, { hint, warn, local, problems }: Pick<Frame, "hint" | "warn" | "local" | "problems">) =>
  [hint !== null ? `${id}-hint` : null, warn ? `${id}-warn` : null, local !== null ? `${id}-local` : null, ...problems.map((_, i) => `${id}-p${i}`)]
    .filter((x): x is string => x !== null)
    .join(" ") || undefined;

function Notes({ id, hint, warn, local, problems }: { id: string } & Pick<Frame, "hint" | "warn" | "local" | "problems">) {
  return (
    <>
      {hint !== null && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
      {warn && <p id={`${id}-warn`} className="text-small text-warn-ink">{warn}</p>}
      {local !== null && <p id={`${id}-local`} className="text-small text-danger">{local}</p>}
      {problems.map((d, i) => (
        <p key={`${d.code}:${i}`} id={`${id}-p${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>
          {d.message}
          {d.fix && <span className="block text-muted">{d.fix}</span>}
        </p>
      ))}
    </>
  );
}

const Required = () => <span className="text-small text-muted">(required)</span>;

export function FieldFrame({ label, required, hint, warn = null, local, problems, actions, below, children }: Frame & {
  below?: ReactNode;
  children: (control: Described) => ReactNode;
}) {  // prettier-ignore
  const id = useId();
  const invalid = local !== null || problems.some((d) => d.severity === "error");
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-baseline gap-1">
          <label htmlFor={id} className="text-small font-semibold">{label}</label>
          {required && <Required />}
        </span>
        {actions}
      </div>
      {children({ id, describedBy: describing(id, { hint, warn, local, problems }), invalid })}
      <Notes id={id} hint={hint} warn={warn} local={local} problems={problems} />
      {below}
    </div>
  );
}

export function GroupFrame({ label, required, hint, local, problems, actions, below, children }: Frame & {
  below?: ReactNode;
  children: ReactNode;
}) {  // prettier-ignore
  const id = useId();
  return (
    <fieldset aria-describedby={describing(id, { hint, local, problems })} className="flex min-w-0 flex-col gap-3">
      <legend className="text-small font-semibold">{label}</legend>
      {required && <Required />}
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      <Notes id={id} hint={hint} local={local} problems={problems} />
      <div className="flex min-w-0 flex-col gap-4 pl-3">{children}</div>
      {below}
    </fieldset>
  );
}
