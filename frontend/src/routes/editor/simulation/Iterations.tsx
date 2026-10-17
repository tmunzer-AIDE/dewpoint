// SPDX-License-Identifier: Apache-2.0
// A loop's iterations, four at a time (4d-1c; the simulation design §7.5; the ResultPanel board; and a run's drawer,
// 4e-1, the RunLoop board): each row, what the loop's own steps did in that iteration, read a page at a time from the
// server's instances (decision 5), never the whole run at once. A failed step opens its instance in that iteration. While the
// next page is read, the one shown stays, with the focus where it was; when a page has no button the person was on
// (the last has no Next, the first no Previous), the focus goes to the other one.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { PAGE, cellOf, iterationOf, type InstancePages } from "./loopBody";

export interface BodyStep {
  id: string;
  key: string;
  type: string;
}

const keyed = (item: unknown): unknown => (typeof item === "object" && item !== null ? (item as Record<string, unknown>).iteration_key : undefined);

export function Iterations({ pages, loop, body, onOpen }: {
  pages: InstancePages; loop: { key: string; prefix: string }; body: BodyStep[]; onOpen?: (stepId: string, iterationKey: string) => void;
}) {  // prettier-ignore
  const [offset, setOffset] = useState(0); // the page asked for
  const [view, setView] = useState(0); // the page shown while the one asked for is read
  const [paged, setPaged] = useState<"next" | "previous" | null>(null); // the button the person paged with
  const next = useRef<HTMLButtonElement>(null);
  const previous = useRef<HTMLButtonElement>(null);
  // One query per page, each step's instances read through `pages` (and kept under their own keys): one observer, so
  // the page shown stays while the next is read (useQueries makes a new observer per key, with nothing to keep).
  const read = useQuery({
    queryKey: ["iterations", ...pages.key, loop.prefix, loop.key, body.map((b) => b.id), offset],
    queryFn: () => Promise.all(body.map((b) => pages.read(b.id, { offset, limit: PAGE, within: loop.prefix || undefined }))),
    placeholderData: keepPreviousData,
  });
  const reading = read.isPlaceholderData;
  useEffect(() => {
    if (!reading) setView(offset);
  }, [reading, offset]);
  useEffect(() => {
    if (paged === null || reading) return;
    const lost = document.activeElement === null || document.activeElement === document.body;
    if (lost) (paged === "next" ? previous : next).current?.focus();
    setPaged(null);
  }, [paged, reading, offset]);
  if (read.isError) {
    return (
      <p className="flex flex-wrap items-center gap-2 text-small">
        The iterations couldn&apos;t be read.
        <Button size="sm" onClick={() => void read.refetch()}>Read them again</Button>
      </p>
    );
  }
  const answers = read.data;
  if (answers === undefined) return <p className="text-small text-muted">Reading the iterations…</p>;
  const total = Math.max(0, ...answers.map((d) => d.total));
  if (total === 0) return <p className="text-small text-muted">No iteration was opened.</p>;
  const at0 = reading ? view : offset; // the first iteration shown
  const shown = Math.max(0, Math.min(PAGE, total - at0));
  const rest = total - at0 - shown;
  const span = `${at0 + 1} to ${at0 + shown} of ${total}`;
  const page = (to: number, by: "next" | "previous") => {
    if (reading) return; // one page at a time
    setPaged(by);
    setOffset(to);
  };
  return (
    <div className="flex flex-col gap-1.5">
      <ol aria-label={`${loop.key}'s iterations, ${span}`} className="flex flex-col text-small">
        {Array.from({ length: shown }, (_, i) => at0 + i).map((n) => {
          const at = iterationOf(loop.prefix, loop.key, n);
          return (
            <li key={n} className="border-t border-line py-1.5 first:border-t-0">
              {n + 1}
              {body.map((b, j) => {
                const c = cellOf(answers[j]?.items.find((item) => keyed(item) === at), b.type);
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
        <span className="grow">{`Iterations ${at0 + 1}–${at0 + shown} of ${total}`}</span>
        {at0 > 0 && <Button ref={previous} size="sm" onClick={() => page(Math.max(0, at0 - PAGE), "previous")}>{`Previous ${PAGE}`}</Button>}
        {rest > 0 && <Button ref={next} size="sm" onClick={() => page(at0 + PAGE, "next")}>{`Next ${Math.min(PAGE, rest)}`}</Button>}
      </p>
    </div>
  );
}
