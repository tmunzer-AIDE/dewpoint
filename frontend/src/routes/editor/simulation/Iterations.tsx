// SPDX-License-Identifier: Apache-2.0
// A loop's iterations in the Simulation panel, four at a time (4d-1c; the simulation design §7.5; the ResultPanel
// board): each row, what the loop's own steps did in that iteration, read a page at a time from the server's
// instances (decision 5), never the whole run at once. A failed step opens its instance in that iteration.
import { useQueries } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Button } from "../../../components/Button";
import { stepInstancesQuery } from "../../../lib/simulations";
import { PAGE, cellOf, iterationOf } from "./loopBody";

export interface BodyStep {
  id: string;
  key: string;
  type: string;
}

const keyed = (item: unknown): unknown => (typeof item === "object" && item !== null ? (item as Record<string, unknown>).iteration_key : undefined);

export function Iterations({ tenantId, workflowId, requestId, loop, body, onOpen }: {
  tenantId: string; workflowId: string; requestId: string; loop: { key: string; prefix: string }; body: BodyStep[];
  onOpen?: (stepId: string, iterationKey: string) => void;
}) {  // prettier-ignore
  const [offset, setOffset] = useState(0);
  const pages = useQueries({
    queries: body.map((b) => stepInstancesQuery(tenantId, workflowId, requestId, b.id, { offset, limit: PAGE, within: loop.prefix || undefined })),
  });
  if (pages.some((p) => p.isError)) {
    return (
      <p className="flex flex-wrap items-center gap-2 text-small">
        The iterations couldn&apos;t be read.
        <Button size="sm" onClick={() => pages.forEach((p) => p.isError && void p.refetch())}>Read them again</Button>
      </p>
    );
  }
  const read = pages.map((p) => p.data);
  if (read.some((d) => d === undefined)) return <p className="text-small text-muted">Reading the iterations…</p>;
  const total = Math.max(0, ...read.map((d) => d!.total));
  if (total === 0) return <p className="text-small text-muted">No iteration was opened.</p>;
  const shown = Math.max(0, Math.min(PAGE, total - offset));
  const rest = total - offset - shown;
  const span = `${offset + 1} to ${offset + shown} of ${total}`;
  return (
    <div className="flex flex-col gap-1.5">
      <ol aria-label={`${loop.key}'s iterations, ${span}`} className="flex flex-col text-small">
        {Array.from({ length: shown }, (_, i) => offset + i).map((n) => {
          const at = iterationOf(loop.prefix, loop.key, n);
          return (
            <li key={n} className="border-t border-line py-1.5 first:border-t-0">
              {n + 1}
              {body.map((b, j) => {
                const c = cellOf(read[j]!.items.find((item) => keyed(item) === at), b.type);
                return (
                  <Fragment key={b.id}>
                    {" · "}
                    <span className="font-mono">{b.key}</span>{" "}
                    <span className={c.failed ? "text-danger" : "text-muted"}>{c.text}</span>
                    {c.code && (
                      <>
                        {" · "}
                        <span className="font-mono text-meta">{c.code}</span>
                      </>
                    )}
                    {c.failed && onOpen && (
                      <>
                        {" "}
                        <Button size="sm" aria-label={`Open ${b.key}, iteration ${n + 1}`} onClick={() => onOpen(b.id, at)}>Open</Button>
                      </>
                    )}
                  </Fragment>
                );
              })}
            </li>
          );
        })}
      </ol>
      <p className="flex flex-wrap items-center gap-2 text-small text-muted">
        <span className="grow">{`Iterations ${offset + 1}–${offset + shown} of ${total}`}</span>
        {offset > 0 && <Button size="sm" onClick={() => setOffset(Math.max(0, offset - PAGE))}>{`Previous ${PAGE}`}</Button>}
        {rest > 0 && <Button size="sm" onClick={() => setOffset(offset + PAGE)}>{`Next ${Math.min(PAGE, rest)}`}</Button>}
      </p>
    </div>
  );
}
