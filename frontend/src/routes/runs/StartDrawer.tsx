// SPDX-License-Identifier: Apache-2.0
// A run's start, opened from its start card (editor 4e-1; the runs design §5.4; the RunOther board), in the editor's
// side drawer: what started it, who and when; its input as its request stored it, read back, sensitive values redacted
// (`absent` once its tenant's retention dropped it, `unreadable` when it doesn't open); a step test's values; and a CSV
// run's file: the rows read, run and skipped, why each skipped row was (the first 100), and the columns it mapped. Its
// heading takes focus as it opens; Escape closes it as Close does.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef } from "react";
import { Button } from "../../components/Button";
import { When } from "../../components/When";
import { runInputQuery, type Run } from "../../lib/runs";
import { SIDE } from "../editor/side";
import { Section, Values } from "./RunResult";
import { triggerOf } from "./trigger";

const SKIPPED = 100; // the skipped rows listed

function Input({ tenantId, run }: { tenantId: string; run: Run }) {
  const read = useQuery(runInputQuery(tenantId, run.id));
  if (read.isPending) return <p className="text-small text-muted">Reading its input…</p>;
  if (read.isError) return <p className="text-small text-muted">Its input couldn&apos;t be read.</p>;
  const { read_back: kept, input, seeds } = read.data;
  if (kept === "absent") return <p className="text-small">Its input isn&apos;t kept any more. The run&apos;s steps and results still are.</p>;
  if (kept === "unreadable") return <p className="text-small">Its input can&apos;t be read back: it doesn&apos;t open, or the tenant&apos;s key is gone during an erasure.</p>;
  return (
    <>
      <p className="text-small text-muted">As the run&apos;s request stored it. Sensitive values are redacted.</p>
      {seeds ? <Values value={seeds} none="None." /> : <Values value={input} none="None." />}
    </>
  );
}

function CsvFile({ csv }: { csv: NonNullable<Run["csv"]> }) {
  const listed = csv.skipped.slice(0, SKIPPED).map((s) => `row ${s.row} ${s.code}`);
  const more = csv.skipped.length - listed.length;
  return (
    <Section title="CSV file">
      <dl className="grid grid-cols-[minmax(0,6rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-small">
        <dt>Rows</dt>
        <dd>{`${csv.row_count} read · ${csv.row_count - csv.skipped.length} run · ${csv.skipped.length} skipped`}</dd>
        {listed.length > 0 && (
          <>
            <dt>Skipped</dt>
            <dd className="font-mono">{`${listed.join(" · ")}${more > 0 ? ` · ${more} more` : ""}`}</dd>
          </>
        )}
        <dt>Columns</dt>
        <dd>{Object.entries(csv.mapping).map(([column, header]) => `${header} → ${column}`).join(", ")}</dd>
      </dl>
    </Section>
  );
}

export function StartDrawer({ tenantId, run, onClose }: { tenantId: string; run: Run; onClose: () => void }) {
  const title = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const trigger = triggerOf(run);
  return (
    <aside
      aria-labelledby={title}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className={`${SIDE} gap-5`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id={title} ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Start</h2>
          <p className="text-small text-muted">
            {trigger.kind}
            {trigger.detail && <> · {trigger.detail}</>}
            {run.queued_at && <> · <When iso={run.queued_at} /></>}
          </p>
        </div>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      <Section title="Input">
        <Input tenantId={tenantId} run={run} />
      </Section>
      {run.csv && <CsvFile csv={run.csv} />}
    </aside>
  );
}
