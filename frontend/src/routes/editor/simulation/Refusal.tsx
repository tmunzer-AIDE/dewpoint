// SPDX-License-Identifier: Apache-2.0
// A simulation refused at admission, in the Simulation panel (4d-1c; the simulation design §7.7; the Refusals board):
// in the server's words, never a catalogue of the client's. A draft's problems ("Fix N problems first", each with Go to,
// and the Problems panel); a declassifying draft without the permission; the deployment's gate; a retired type (Go to
// each step of it); no current build (Try again: a refusal is never recorded, so the same request can be sent again);
// a step test's values by their pointer; the draft changed elsewhere. Nothing ran. The Test tab shows a draft's problems
// before anything is tried, without "Not simulated" (`heading` null).
import { Button } from "../../../components/Button";
import type { ApiError } from "../../../lib/client";
import { findNode, nodesOf } from "../../../lib/graph";
import type { Diagnostic, GraphDoc } from "../../../lib/workflows";

const DECLASSIFY = "declassify.forbidden";

export function Refusal({ error, doc, heading = "Not simulated", onGoTo, onShowProblems, onTryAgain }: {
  error: ApiError; doc: GraphDoc; heading?: string | null; onGoTo: (stepId: string) => void; onShowProblems: () => void;
  onTryAgain: () => void;
}) {  // prettier-ignore
  const body = (typeof error.body === "object" && error.body !== null ? error.body : {}) as {
    diagnostics?: Diagnostic[]; messages?: unknown; problems?: { pointer: string; message: string }[];
  };  // prettier-ignore
  const messages = Array.isArray(body.messages) ? body.messages.filter((m): m is string => typeof m === "string") : [];
  const goTo = (id: string, key: string) => (
    <Button size="sm" aria-label={`Go to ${key}`} onClick={() => onGoTo(id)}>Go to</Button>
  );

  let said;
  if (error.code === "invalid") {
    const errors = (body.diagnostics ?? []).filter((d) => d.severity === "error");
    said = errors.every((d) => d.code === DECLASSIFY) ? (
      errors.map((d, i) => <p key={i}>{d.message}</p>)
    ) : (
      <>
        <p>{`Fix ${errors.length} ${errors.length === 1 ? "problem" : "problems"} first: a draft with problems isn't simulated.`}</p>
        <ul aria-label="Problems" className="flex flex-col">
          {errors.map((d, i) => {
            const step = d.node ? findNode(doc, d.node) : undefined;
            return (
              <li key={i} className="flex flex-wrap items-center gap-2 border-t border-line py-1.5 first:border-t-0">
                <span className="grow">
                  {step && <span className="font-mono">{step.key}</span>}
                  {step && " · "}
                  <span>{d.message}</span>
                </span>
                {step && goTo(step.id, step.key)}
              </li>
            );
          })}
        </ul>
        <div>
          <Button size="sm" onClick={onShowProblems}>Show the problems</Button>
        </div>
      </>
    );
  } else if (error.code === "draft_conflict") {
    said = <p>The draft was changed elsewhere, so it wasn&apos;t simulated.</p>;
  } else if (Array.isArray(body.problems)) {
    said = (
      <ul className="flex flex-col gap-1">
        {body.problems.map((p, i) => <li key={i}>{`${p.pointer}: ${p.message}`}</li>)}
      </ul>
    );
  } else if (messages.length > 0) {
    const retired = error.code === "node_type_retired" ? nodesOf(doc).filter((n) => messages.some((m) => m.startsWith(`${n.type} `))) : [];
    said = (
      <>
        {messages.map((m, i) => <p key={i}>{m}</p>)}
        {retired.length > 0 && <div className="flex flex-wrap gap-2">{retired.map((n) => <Button key={n.id} size="sm" onClick={() => onGoTo(n.id)}>{`Go to ${n.key}`}</Button>)}</div>}
        {error.code === "no_current_build" && (
          <div>
            <Button size="sm" onClick={onTryAgain}>Try again</Button>
          </div>
        )}
      </>
    );
  } else {
    said = <p>{`The server refused it: ${error.code}.`}</p>;
  }
  return (
    <div className="flex flex-col gap-2 text-small">
      {heading && <p className="font-semibold">{heading}</p>}
      {said}
    </div>
  );
}
