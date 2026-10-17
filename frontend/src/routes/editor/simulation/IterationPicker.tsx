// SPDX-License-Identifier: Apache-2.0
// One iteration of a step that ran in a loop, picked (4d-1c; the simulation design §7.6's iteration picker; and a run's
// drawer, 4e-1, the RunLoop board): from the first page of its instances, in iteration order, or the one a loop's
// "Open" asked for, read on its own when it's past that page. Show shows it.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { Select } from "../../../components/Field";
import type { InstancePages } from "./loopBody";
import { field } from "./results";

const PAGE = 50;

/** An iteration as a person counts it: from 1, nested ones joined ("2/3"). */
export const counted = (key: string) => key.split("/").map((part) => Number(part.split(":").at(-1)) + 1).join("/");
const keyOf = (item: unknown) => {
  const key = field(item, "iteration_key");
  return typeof key === "string" ? key : "";
};
function optionOf(item: unknown): string {
  const status = field(item, "status");
  const code = field(field(item, "error"), "code");
  return `${counted(keyOf(item))} · ${typeof status === "string" ? status.replace("_", " ") : "not recorded"}${typeof code === "string" ? ` · ${code}` : ""}`;
}

/** `iteration`: one asked for (counted, so the same one asked again shows again); `beyond`: what the caption adds when
 * there are more than the first page; `show`: an instance, by its counted iteration. */
export function IterationPicker({ pages, stepId, iteration, beyond, show }: {
  pages: InstancePages; stepId: string; iteration: { key: string; n: number } | null; beyond?: string;
  show: (item: unknown, iteration: string) => ReactNode;
}) {  // prettier-ignore
  const page = useQuery({ queryKey: ["iteration-picker", ...pages.key, stepId], queryFn: () => pages.read(stepId, { offset: 0, limit: PAGE }) });
  const [picked, setPicked] = useState<string | null>(iteration?.key ?? null);
  const [shown, setShown] = useState<string | null>(iteration?.key ?? null);
  useEffect(() => {
    if (iteration) {
      setPicked(iteration.key);
      setShown(iteration.key);
    }
  }, [iteration?.n]);
  const first = page.data?.items ?? [];
  const askedPast = iteration !== null && page.data !== undefined && !first.some((i) => keyOf(i) === iteration.key);
  const asked = useQuery({
    queryKey: ["iteration-picker", ...pages.key, stepId, iteration?.key ?? null],
    queryFn: () => pages.read(stepId, { offset: 0, limit: 1, within: iteration?.key }),
    enabled: askedPast,
  });
  if (page.isError) return <p className="text-small text-muted">Its iterations couldn&apos;t be read.</p>;
  if (!page.data) return <p className="text-small text-muted">Reading its iterations…</p>;
  const items = askedPast && asked.data ? [...first, ...asked.data.items.filter((i) => keyOf(i) === iteration?.key)] : first;
  const choice = picked ?? (items[0] ? keyOf(items[0]) : "");
  const item = shown === null ? undefined : items.find((i) => keyOf(i) === shown);
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 grow">
          <Select label="Iteration" value={choice} onChange={(e) => setPicked(e.target.value)}>
            {items.map((i) => <option key={keyOf(i)} value={keyOf(i)}>{optionOf(i)}</option>)}
          </Select>
        </div>
        <Button size="md" onClick={() => setShown(choice || null)}>Show</Button>
      </div>
      {page.data.total > first.length && (
        <p className="text-small text-muted">{`The first ${first.length} of ${page.data.total} iterations.${beyond ? ` ${beyond}` : ""}`}</p>
      )}
      {item !== undefined && show(item, counted(keyOf(item)))}
    </>
  );
}
