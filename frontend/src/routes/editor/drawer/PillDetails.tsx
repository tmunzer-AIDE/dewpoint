// SPDX-License-Identifier: Apache-2.0
// A pill's details (4c-2b, the mockups' details and sample boards): opened from a focused pill with Enter, never on
// hover. What it reads, its type, why it may be missing; a default when it's in text (a template part's); and, from
// the newest run that gave it (B7), the value as the run's preview kept it, with that run, its attempt, its connection
// and whether the step still matches. In the drawer, under its field. Samples show only here (the owner's ruling).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { DraftMoved, previewAt, samplesQuery, tagsOf, typeWords, whyMissing, type Sample } from "../../../lib/data";
import { headOf, parsePath, type Pill } from "../../../lib/pills";
import { useDrawer } from "./context";
import { usePillEntry } from "./Pill";

/** A preview's marker, as a chip: never the value it stands for (D20). */
const Chip = ({ children }: { children: ReactNode }) => (
  <span className="rounded-sm border border-line-strong px-1.5 font-mono text-meta text-muted">{children}</span>
);

/** A JSON value as the preview kept it, each `[redacted]` and `[truncated]` a chip where it was. */
export function PreviewValue({ value }: { value: unknown }): ReactNode {
  if (typeof value === "string") {
    const parts = value.split(/(\[redacted\]|\[truncated\])/);
    return (
      <>
        &quot;
        {parts.map((p, i) => (p === "[redacted]" ? <Chip key={i}>redacted</Chip> : p === "[truncated]" ? <Chip key={i}>truncated</Chip> : p))}
        &quot;
      </>
    );
  }
  if (Array.isArray(value)) {
    return (
      <>
        [
        {(value as unknown[]).map((v, i) => (
          <span key={i}>
            {i > 0 && ", "}
            <PreviewValue value={v} />
          </span>
        ))}
        ]
      </>
    );
  }
  if (typeof value === "object" && value !== null) {
    return (
      <>
        {"{ "}
        {Object.entries(value as Record<string, unknown>).map(([k, v], i) => (
          <span key={k}>
            {i > 0 && ", "}&quot;{k}&quot;: <PreviewValue value={v} />
          </span>
        ))}
        {" }"}
      </>
    );
  }
  return <>{JSON.stringify(value)}</>;
}

const when = (iso: string | null): string => {
  if (iso === null) return "time not recorded";
  const at = new Date(iso);
  return at.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
};

function SampleView({ sample, rest, stepKey, searched, limit }: {
  sample: Sample | null; rest: (string | number)[]; stepKey: string; searched: number; limit: number;
}) {  // prettier-ignore
  if (sample === null) {
    return (
      <p className="text-small text-muted">
        {searched === 0
          ? `This workflow hasn't finished a run yet, so ${stepKey} has no sample.`
          : searched < limit
            ? `${stepKey} hasn't succeeded in a run of this workflow yet. Its type, and whether it may be missing, come from its schema.`
            : `${stepKey} hasn't succeeded in the newest ${limit} finished runs of this workflow.`}
      </p>
    );
  }
  const found = previewAt(sample.output, rest);
  const c = sample.connections;
  return (
    <div className="flex flex-col gap-2">
      <div className="break-all rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-small">
        {"value" in found ? <PreviewValue value={found.value} />
          : found.marker === "absent" ? "Not in this run's output."
          : found.marker === "claimed" ? "Kept apart from the run's history, so not in its preview."
          : <Chip>{found.marker}</Chip>}
      </div>
      {"marker" in found && found.marker === "truncated" && (
        <p className="text-small text-muted">This step&apos;s output was over 8 KiB, so no preview of it was kept. The output itself went on to the next steps as usual.</p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small">
        <dt className="text-muted">Run</dt>
        <dd className="font-mono">
          {sample.run_id.slice(0, 8)} · version {sample.version_number} · {sample.mode === "simulate" ? "simulated" : "live"}
          {sample.run_kind === "subflow" ? " · as a sub-flow" : sample.run_kind === "failure_handler" ? " · as a failure handler" : ""} · succeeded
        </dd>
        <dt className="text-muted">Attempt</dt>
        <dd>{sample.attempt} · {when(sample.captured_at)}{sample.iteration_key !== "" ? ` · iteration ${sample.iteration_key}` : ""}</dd>
        {c.state !== "none" && (
          <>
            <dt className="text-muted">Connection</dt>
            <dd>
              {c.state === "simulated"
                ? "None: a simulation sends nothing."
                : c.state === "unknown"
                  ? "Unknown: this run is from before connections were recorded."
                  : c.items.map((x) => (
                      <span key={`${x.connection_id}:${x.revision}`} className="block">
                        {x.name} ({x.type}) ·{" "}
                        {x.state === "unchanged"
                          ? "unchanged since"
                          : x.state === "deleted"
                            ? "deleted since"
                            : `revision ${x.revision} then, ${x.current_revision} now`}
                      </span>
                    ))}
            </dd>
          </>
        )}
      </dl>
      {!sample.same_type ? (
        <p className="text-small text-ink">{stepKey} is another type of step now, so this sample may not match what it gives.</p>
      ) : !sample.same_config ? (
        <p className="text-small text-ink">{stepKey}&apos;s settings have changed since this run, so this sample may not match what it gives now.</p>
      ) : sample.stale ? (
        <p className="text-small text-ink">Its connection has changed since this run, so this sample may not match what it gives now.</p>
      ) : null}
    </div>
  );  // prettier-ignore
}

export function PillDetails({ field, pill, defaults, onDefault, onReplace, onRemove, onClose }: {
  field: string; pill: Pill; defaults: boolean; onDefault: (value: string | null | undefined) => void;
  onReplace: () => void; onRemove: () => void; onClose: () => void;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const { entry, stale, problem } = usePillEntry(pill.ref, field);
  const heading = useId();
  const defaultId = useId();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.querySelector<HTMLElement>("h3")?.focus(), []);
  // Adding a default focuses it, removing one focuses "Add a default…": the pressed button goes (the final review).
  const want = useRef<"default" | "add" | null>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (want.current === "default" && "default" in pill) document.getElementById(defaultId)?.focus();
    else if (want.current === "add" && !("default" in pill)) (addButton.current ?? box.current?.querySelector<HTMLElement>("h3"))?.focus();
    else return;
    want.current = null;
  });
  const parts = parsePath(pill.ref) ?? [];
  const head = headOf(pill.ref).head;
  const isStep = parts.length >= 3 && "field" in parts[0]! && parts[0].field === "steps" && "field" in parts[2]! && parts[2].field === "output";
  const step = isStep ? drawer.steps.find((s) => s.key === head) : undefined;
  const rest = parts.slice(3).map((p) => ("field" in p ? p.field : p.index));
  const samples = useQuery({
    ...samplesQuery({ tenantId: drawer.tenantId, workflowId: drawer.workflowId, revision: drawer.revision ?? -1, node: step?.id ?? "" }),
    enabled: drawer.revision !== null && step !== undefined,
  });  // prettier-ignore
  const reasons = entry ? whyMissing(entry) : [];
  const editable = drawer.editable;
  return (
    <div
      ref={box} role="dialog" aria-labelledby={heading}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // closes the details, not the drawer
          onClose();
        }
      }}
      className="flex flex-col gap-3 rounded-lg border border-line-strong bg-surface p-3.5"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 id={heading} tabIndex={-1} className="break-all font-mono text-small font-semibold outline-none">{pill.ref}</h3>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {problem && <p className="text-small text-danger">{problem}</p>}
      {/* Saved again: its facts are this revision's only once its answer comes (the review of the final checkpoint). */}
      {stale && <p className="text-small text-muted">Checking the saved draft&apos;s data…</p>}
      {entry && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small">
          <dt className="text-muted">Type</dt>
          <dd>{typeWords(entry)}</dd>
          <dt className="text-muted">When it runs</dt>
          <dd className="flex flex-wrap items-center gap-1.5">
            {tagsOf(entry).map((t) => (
              <span key={t.text} className={`rounded-sm border px-1.5 text-meta ${t.conditional ? "border-dashed border-warn-line bg-warn-bg text-warn-ink" : "border-line-strong text-muted"}`}>{t.text}</span>
            ))}
            {reasons.length > 0 ? reasons.join("; ") : "always there"}
          </dd>
        </dl>
      )}
      {/* A default written shows whatever the value is now, and in a version's view (the final review); one is
          offered only for a value that may be missing or null. */}
      {defaults && ("default" in pill || (entry && (entry.missing || entry.nullable))) && (
        <div className="flex flex-col gap-1.5">
          {"default" in pill ? (
            <>
              <label htmlFor={defaultId} className="text-small font-semibold">If it&apos;s missing or null</label>
              <input
                id={defaultId} type="text" value={pill.default ?? ""} disabled={!editable} aria-describedby={`${defaultId}-note`}
                onChange={(e) => onDefault(e.target.value)} className={controlClass(false)}
              />
              <p id={`${defaultId}-note`} className="text-small text-muted">
                Used when the value is missing or null. Empty text, 0, false and empty lists are values, so they&apos;re kept. A
                default doesn&apos;t change what&apos;s sensitive: if the value is, the result still is.
              </p>
              {entry && !entry.missing && !entry.nullable && (
                <p className="text-small text-muted">It&apos;s always there now, so this default isn&apos;t used.</p>
              )}
              {editable && (
                <div>
                  <Button size="sm" onClick={() => { want.current = "add"; onDefault(undefined); }}>Remove the default</Button>
                </div>
              )}
            </>
          ) : editable ? (
            <div><Button ref={addButton} size="sm" onClick={() => { want.current = "default"; onDefault(""); }}>Add a default…</Button></div>
          ) : (
            <p className="text-small text-muted">No default: when it&apos;s missing, the text has nothing there.</p>
          )}
        </div>
      )}
      {isStep && (
        <section aria-label="From a past run" className="flex flex-col gap-2">
          <h4 className="text-small font-semibold">From a past run</h4>
          {drawer.revision === null ? (
            // A version's view asks nothing (ruling 130): its query never runs, so it's never "looking".
            <p className="text-small text-muted">A version&apos;s data isn&apos;t shown: open the draft to see a past run&apos;s sample.</p>
          ) : step === undefined ? (
            // Its step was deleted or renamed: no sample is asked for, so it's never "looking" (the final review).
            <p className="text-small text-muted">{head} isn&apos;t a step of this draft, so it has no sample.</p>
          ) : samples.isPending ? (
            <p className="text-small text-muted">Looking for a sample…</p>
          ) : samples.isError ? (
            <p className="text-small text-muted">{samples.error instanceof DraftMoved ? samples.error.message : "The sample couldn't be loaded."}</p>
          ) : (
            <SampleView sample={samples.data.sample} rest={rest} stepKey={head} searched={samples.data.searched_runs} limit={samples.data.search_limit} />
          )}
        </section>
      )}
      {editable && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onReplace}>Replace…</Button>
          <Button size="sm" variant="danger" onClick={onRemove}>Remove</Button>
        </div>
      )}
    </div>
  );  // prettier-ignore
}
