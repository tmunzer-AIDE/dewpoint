// SPDX-License-Identifier: Apache-2.0
// The draft's problems (outline §2's validate and publish; engine-core §5.10). The server's messages and fixes, as
// it wrote them: there's no catalogue in the client. A step's problem goes to the step (4b ruling 16). What the check
// says is dated (ruling 24): "none found" only for a current check. What only publish checks shows apart, marked, and
// dated against the edits since (ruling 17).
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import type { Diagnostic, Validation } from "../../lib/workflows";
import type { CheckState } from "./check";
import { SIDE } from "./side";

/** What only publish found, with the snapshot it was found in: the saved revision, and the editor's generation. */
export type PublishProblems = { revision: number; generation: number; diagnostics: Diagnostic[] };

function Problem({ d, keyOf, onJump }: { d: Diagnostic; keyOf: (id: string) => string; onJump: (id: string) => void }) {
  return (
    <li className="flex flex-col gap-0.5 border-t border-line py-2.5 text-small first:border-t-0">
      <span className={d.severity === "error" ? "text-danger" : "text-warn-ink"}>
        {d.severity === "error" ? "Error" : "Warning"}: {d.message}
      </span>
      {d.fix && <span className="text-muted">{d.fix}</span>}
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-meta text-muted">{d.code}{d.field ? ` · ${d.field}` : ""}</span>
        {d.node && (
          <Button size="sm" onClick={() => onJump(d.node!)}>
            Go to {keyOf(d.node)}
          </Button>
        )}
      </span>
    </li>
  );
}

const ordered = (ds: Diagnostic[]) => [...ds.filter((d) => d.severity === "error"), ...ds.filter((d) => d.severity !== "error")];

const NOTES: Record<Exclude<CheckState, "current">, string> = {
  unchecked: "Not checked yet.",
  checking: "Checking the saved draft…",
  failed: "The check failed, so what's below may be out of date.",
  stale: "From a check made before your latest edits: they may have changed this.",
};

export function ProblemsPanel({
  state, validation, publishProblems, publishCurrent, keyOf, onJump, onCheck, onClose,
}: {
  state: CheckState; validation: Validation | null; publishProblems: PublishProblems | null; publishCurrent: boolean;
  keyOf: (id: string) => string; onJump: (nodeId: string) => void; onCheck: () => void; onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const separate = validation?.expressions.filter((x) => x.mode === "activity") ?? [];
  const inline = (validation?.expressions.length ?? 0) - separate.length;
  return (
    <aside
      aria-labelledby="problems-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className={`${SIDE} gap-5`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="problems-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Problems</h2>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {state !== "current" && (
        <p className="flex flex-wrap items-center gap-2 text-small text-muted">
          {NOTES[state]}
          {state === "failed" && <Button size="sm" onClick={onCheck}>Check again</Button>}
        </p>
      )}
      {validation && validation.diagnostics.length > 0 && (
        <ul>{ordered(validation.diagnostics).map((d, i) => <Problem key={`${d.code}:${d.node}:${d.field}:${i}`} d={d} keyOf={keyOf} onJump={onJump} />)}</ul>
      )}
      {state === "current" && validation?.diagnostics.length === 0 && (
        <p className="text-small text-muted">None found in the saved draft. Publishing checks a few more things.</p>
      )}
      {publishProblems && (
        <section aria-labelledby="publish-problems" className="flex flex-col gap-1">
          <h3 id="publish-problems" className="text-small font-semibold">Found at publish</h3>
          <p className="text-small text-muted">
            {publishCurrent
              ? "Publishing checks connections, sub-flows and lifecycles too."
              : "From the last publish attempt, before your latest edits."}
          </p>
          <ul>{ordered(publishProblems.diagnostics).map((d, i) => <Problem key={`p:${d.code}:${d.node}:${i}`} d={d} keyOf={keyOf} onJump={onJump} />)}</ul>
        </section>
      )}
      {validation && validation.expressions.length > 0 && (
        <section aria-labelledby="expressions-title" className="flex flex-col gap-1.5">
          <h3 id="expressions-title" className="text-small font-semibold">How expressions run</h3>
          <ul className="flex flex-col gap-1.5 text-small">
            {separate.map((x) => (
              <li key={`${x.node}:${x.field}`}>
                <span className="font-mono text-meta">{x.node ? keyOf(x.node) : "outputs"} · {x.field}</span>{" "}
                Runs as a separate step: {x.reason ?? "no reason given"}
              </li>
            ))}
          </ul>
          {inline > 0 && <p className="text-small text-muted">{inline === 1 ? "1 expression runs inline." : `${inline} expressions run inline.`}</p>}
        </section>
      )}
    </aside>
  );
}
