// SPDX-License-Identifier: Apache-2.0
// A workflow's schedules (4c-3b; the Schedules and Rules boards): live rows on the published version, saved at once,
// outside undo. Each says its timing in words, its zone where one applies, its mode, and what its sync proves; turning
// one off or deleting it stops new runs at once. One can't be added before a first publish, nor to a workflow that
// takes a CSV file (`409 csv_required`). What the draft would break, the server's check says (4c-3a ruling 7).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { LoadError } from "../../../components/LoadError";
import { Switch } from "../../../components/Switch";
import { announce } from "../../../lib/announce";
import {
  deleteSchedule, missesNote, scheduleMeta, scheduleNote, schedulesQuery, scheduleTitle, startFormQuery, updateSchedule,
  type Schedule,
} from "../../../lib/triggers";  // prettier-ignore
import { useTriggers } from "./context";
import { Section, useFocusBack } from "./parts";
import { ScheduleForm } from "./ScheduleForm";

const LIVE =
  "A change is saved at once. Turning a schedule off, or deleting it, stops new runs at once; turning it on lets its firings through at once. Its mode and input apply from its next firing. The scheduler's timer follows on its own, usually within seconds: until that's confirmed, the previous time may still fire, and a new schedule may already fire.";

/** What validate found a schedule's stored input wouldn't fit in the draft (4c-3a ruling 7), in a sentence. */
function breakWords(reasons: string[], more: boolean): string {
  const said = reasons.map((r) => r.replace(/\.$/, "")).join("; ");
  return `Publishing this draft would make it fail each time: its stored input doesn't fit the draft's input (${said}${more ? "; and more" : ""}). After publishing, replace its input; or change the draft's input back.`;
}

export function SchedulesSection() {
  const t = useTriggers();
  const qc = useQueryClient();
  const schedules = useQuery(schedulesQuery(t.tenantId, t.workflowId));
  // The published version's form: what a schedule's input is entered on, and whether it takes a CSV file.
  const form = useQuery({ ...startFormQuery(t.tenantId, t.workflowId), enabled: t.manage && t.activeNumber !== null });
  const [open, setOpen] = useState<string | null>(null); // "new", or the id of the one being edited (a UUID)
  const [deleting, setDeleting] = useState<Schedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const adder = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const { box, back } = useFocusBack<HTMLElement>(); // an edited schedule's Edit, once its form closes (the final review)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["workflows", t.tenantId] });
    return qc.invalidateQueries({ queryKey: ["schedules", t.tenantId, t.workflowId] });
  };
  const toggle = useMutation({
    mutationFn: (s: { id: string; title: string; enabled: boolean }) => updateSchedule(t.tenantId, s.id, { enabled: s.enabled }),
    onMutate: () => setError(null),
    onSuccess: (_, s) => announce(`${s.title}: ${s.enabled ? "on: its firings start runs again" : "off: it starts no new runs"}`),
    onError: (_, s) => setError(`${s.title} couldn't be switched ${s.enabled ? "on" : "off"}. Try again.`),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (s: Schedule) => deleteSchedule(t.tenantId, s.id),
    onMutate: () => setError(null),
    onSuccess: async (_, s) => {
      setDeleting(null);
      setOpen(null);
      announce(`Deleted the schedule ${scheduleTitle(s)}`);
      await refresh();
      requestAnimationFrame(() => heading.current?.focus());
    },
    onError: (_, s) => {
      setDeleting(null);
      setError(`${scheduleTitle(s)} couldn't be deleted. Try again.`);
    },
  });
  const published = t.activeNumber !== null;
  const csv = form.data?.csv != null;
  const why = !published
    ? "A schedule runs the published version: publish a first version to add one."
    : csv ? "It takes a CSV file: its rows come from an upload, so it can't run on a schedule." : null;  // prettier-ignore
  const list = schedules.data?.schedules ?? [];
  const breaks = new Map((t.check?.schedule_breaks ?? []).map((b) => [b.schedule_id, b]));
  const close = (focusAdd = true) => {
    setOpen(null);
    if (focusAdd) requestAnimationFrame(() => adder.current?.focus());
  };
  return (
    <Section id="triggers-schedules" title="Schedules" heading={heading} box={box} note={published ? `Live · on version ${t.activeNumber}` : "Live"}>
      {list.length > 0 && <p className="text-small text-muted">{LIVE}</p>}
      {error && <p role="alert" className="text-small text-danger">{error}</p>}
      {schedules.isError && <LoadError what="The schedules" />}
      {schedules.isSuccess && list.length === 0 && <p className="text-small text-muted">No schedule starts this workflow.</p>}
      <ul className="flex flex-col">
        {list.map((s) => {
          const title = scheduleTitle(s);
          const note = scheduleNote(s);
          const missed = missesNote(s);
          const broken = breaks.get(s.id);
          return (
            <li key={s.id} className="flex flex-col gap-1.5 border-t border-line py-2.5 first:border-t-0">
              {open === s.id && form.data ? (
                <ScheduleForm
                  schedule={s} form={form.data} activeNumber={t.activeNumber!}
                  onDone={(saved) => {
                    close(false);
                    back(`schedule:${s.id}`);
                    if (saved) void refresh();
                  }}
                  onDelete={() => setDeleting(s)}
                />
              ) : (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 text-body font-medium">{title}</span>
                    <span className="flex items-center gap-2">
                      {t.manage ? (
                        <>
                          <Switch checked={s.enabled} label={title} disabled={toggle.isPending} onCheckedChange={(enabled) => toggle.mutate({ id: s.id, title, enabled })} />
                          <Button size="sm" aria-label={`Edit ${title}`} data-back={`schedule:${s.id}`} disabled={!form.data} onClick={() => setOpen(s.id)}>Edit</Button>
                        </>
                      ) : (
                        <span className="text-small">{s.enabled ? "On" : "Off"}</span>
                      )}
                    </span>
                  </div>
                  <span className="text-small text-muted">{scheduleMeta(s)}</span>
                  {note && <span className={`text-small ${s.sync_error ? "text-danger" : "text-ink"}`}>{note}</span>}
                  {missed && <span className="text-small text-warn-ink">{missed}</span>}
                  {broken && (
                    <span className="text-small text-warn-ink">
                      {breakWords(broken.reasons, broken.more)} The check is the server&apos;s: it reads the schedule&apos;s stored input, which nobody sees.
                    </span>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
      {open === "new" && form.data ? (
        <ScheduleForm schedule={null} form={form.data} activeNumber={t.activeNumber!} onDone={(saved) => {
          close();
          if (saved) void refresh();
        }} />
      ) : t.manage ? (
        <div className="flex flex-col gap-1">
          <Button ref={adder} size="sm" className="self-start" disabled={why !== null || !form.data} aria-describedby={why ? "triggers-no-schedule" : undefined} onClick={() => setOpen("new")}>
            ＋ Schedule
          </Button>
          {why && <p id="triggers-no-schedule" className="text-small text-muted">{why}</p>}
          {published && form.isError && <p className="text-small text-danger">The published version&apos;s form couldn&apos;t be read, so a schedule can&apos;t be added now.</p>}
        </div>
      ) : null}
      <ConfirmDialog
        open={deleting !== null} title={deleting ? `Delete the schedule "${scheduleTitle(deleting)}"?` : ""} confirmLabel="Delete the schedule"
        busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onCancel={() => setDeleting(null)}
      >
        The runs it would start won&apos;t be, from now on. Runs it started stay in the run history.
      </ConfirmDialog>
    </Section>
  );  // prettier-ignore
}
