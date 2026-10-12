// SPDX-License-Identifier: Apache-2.0
// What a step's failure does, in words (4c-1, ruling 10; §10.3's chip), with the attempts and timeout the step sets
// when they differ from its type's.
import { useRef } from "react";
import { Button } from "../../../components/Button";
import { Field, Select } from "../../../components/Field";
import type { StepOptions } from "../../../lib/config";
import { STALE, limitProblem, type Limit } from "../../../lib/unapplied";
import type { GraphNode, NodeType } from "../../../lib/workflows";
import { useDrawer, useSession } from "./context";
import { useText } from "./scalars";

const CHIP = { fail: "fail the run", continue: "continue", port: "route to the error port" } as const;

export function chipText(node: GraphNode, type: NodeType | undefined): string {
  const own = node.options ?? {};
  const parts = [`On error: ${CHIP[own.on_error ?? "fail"]}`];
  if (own.max_attempts != null && own.max_attempts !== type?.retry.max_attempts) {
    parts.push(`${own.max_attempts} ${own.max_attempts === 1 ? "attempt" : "attempts"}`);
  }
  if (own.timeout_s != null && own.timeout_s !== type?.timeout_s) parts.push(`${own.timeout_s} s`);
  return parts.join(" · ");
}

/** A limit the step sets for itself: empty takes the type's. The graph's bounds are checked here, since a draft
 * breaking them isn't saved at all (ruling 7); text they refuse is held, with why (ruling 18). */
function LimitField({ name, label, fallback }: { name: Limit; label: string; fallback: string }) {
  const drawer = useDrawer();
  const own = drawer.node.options ?? {};
  const pointer = `/options/${name}`;
  const held = drawer.held("limit", pointer);
  const { mark, onFocus } = useSession(`${drawer.node.id}${pointer}`);
  const [text, setText] = useText(
    own[name] ?? undefined,
    (v) => (typeof v === "number" ? String(v) : ""),
    (t, v) => (t.trim() === "" ? v === undefined : Number(t) === v),
    held?.text,
  );
  const stale = held !== undefined && drawer.stale("limit", pointer);
  const box = useRef<HTMLDivElement>(null);
  // Its Apply here and Discard go with the edit: focus goes back to the limit (WCAG 2.4.3; the final review).
  const refocus = () => requestAnimationFrame(() => box.current?.querySelector("input")?.focus());
  return (
    <div ref={box} onFocus={onFocus} data-limit={name} className="flex flex-col gap-1.5">
      <Field
        label={label} hint={`If empty: ${fallback}.`} error={stale ? STALE : (held?.why ?? undefined)} value={held?.text ?? text}
        disabled={!drawer.editable}
        onChange={(e) => {
          const typed = e.target.value;
          setText(typed);
          const t = typed.trim();
          // Typed over a limit that has since changed (an undo): never written unasked (ruling 18).
          const why = limitProblem(name, typed) ?? (stale ? STALE : drawer.options({ ...own, [name]: t === "" ? undefined : Number(t) }, mark()));
          // Released only once it's written; refused, it stays the person's, with why (ruling 18).
          if (why === null) drawer.release("limit", pointer);
          else drawer.hold("limit", pointer, { path: [name], label, text: typed, why });
        }}
      />
      {held && drawer.editable && (
        <div className="flex flex-wrap gap-2">
          {stale && (
            <Button
              size="sm" aria-label={`Apply here: ${label}`}
              onClick={() => {
                drawer.rebase("limit", pointer);
                drawer.apply("limit", pointer);
                refocus();
              }}
            >
              Apply here
            </Button>
          )}
          <Button
            size="sm" aria-label={`Discard the edit to ${label}`}
            onClick={() => {
              drawer.release("limit", pointer);
              setText(typeof own[name] === "number" ? String(own[name]) : "");
              refocus();
            }}
          >
            Discard
          </Button>
        </div>
      )}
    </div>
  );  // prettier-ignore
}

/** The chip's section (ruling 10): what a failure does, then the attempts and the timeout. */
export function ErrorHandling() {
  const drawer = useDrawer();
  const type = drawer.type;
  if (!type) return null; // a type this server doesn't know: its options are kept, not shown
  const own = drawer.node.options ?? {};
  return (
    <section id="error-handling" aria-label="Error handling" className="flex flex-col gap-4">
      <Select
        label="When it fails" value={own.on_error ?? "fail"} disabled={!drawer.editable}
        onChange={(e) => drawer.options({ ...own, on_error: e.target.value as StepOptions["on_error"] })}
      >
        <option value="fail">Fail the run</option>
        <option value="continue">Continue with the next step</option>
        <option value="port">Route to an error port</option>
      </Select>
      <LimitField name="max_attempts" label="Attempts" fallback={String(type.retry.max_attempts)} />
      <LimitField name="timeout_s" label="Timeout (seconds)" fallback={`${type.timeout_s} s`} />
    </section>
  );  // prettier-ignore
}
