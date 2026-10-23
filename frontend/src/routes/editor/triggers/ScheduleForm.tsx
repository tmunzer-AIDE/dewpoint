// SPDX-License-Identifier: Apache-2.0
// A schedule's form (4c-3b; the ScheduleForm, ScheduleWhen and NarrowForms boards): when it runs (a preset, or a cron),
// its time zone where one applies, its mode, how late a missed firing still starts, and its input on the published
// version's form. Editing one never shows its stored input back: it's kept, or replaced whole. Its timing is sent only
// when changed here, and one no preset says is kept as it is (the review of revision 1). The input is entered whole, as
// JSON, where its rules are more than the form's fields show, or on request (the review of revision 2): how is settled
// before anything is typed, what's typed goes with it from one way to the other, JSON a parse would change is refused,
// and every key is kept as typed (the review of revision 3). Saved at once; the API checks the timing and the input
// (each refusal said at its field). A picker field lists the choices of the version whose input it shows, and the
// names of the picks the input still holds go with it, never alone (the 4f-3 design §5.3, §5.5).
import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { Field, Select, TextArea } from "../../../components/Field";
import { PickerProvider, namesFor, usePicks, versionChoices } from "../pickerField";
import { InputControl, fieldKey, fieldsShow, fromFields, listed, shownOf, startValues, wholeOf } from "../startInput";
import { announce } from "../../../lib/announce";
import { ApiError } from "../../../lib/client";
import { CATCHUP, TIMING_WORDS, blankWhen, intervalWords, timingOf, whenOf, zones, type Preset, type When } from "../../../lib/timing";
import { asGraph } from "../../../lib/graph";
import { inputOf } from "../../../lib/input";
import { createSchedule, scheduleTitle, updateSchedule, versionQuery, type Schedule, type StartForm } from "../../../lib/triggers";
import { useTriggers } from "./context";

const PRESETS: { value: Preset; label: string }[] = [
  { value: "minutes", label: "Every N minutes" },
  { value: "hours", label: "Every N hours" },
  { value: "daily", label: "Every day at" },
  { value: "weekdays", label: "Weekdays at" },
  { value: "custom", label: "Custom (cron)" },
];
const BROWSER_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** Where the API's refusal of a timing field shows in the form. */
function fieldOfProblem(field: string, preset: Preset): keyof When | "zone" | "catchup" | "when" {
  if (field === "time_zone") return "zone";
  if (field === "catchup_window_s") return "catchup";
  if (field === "every_s") return "every";
  if (field === "offset_s") return preset === "hours" ? "first" : "past";
  return preset === "custom" ? "cron" : preset === "daily" || preset === "weekdays" ? "time" : "when";
}

/** Whether two "When"s say the same, field for field. */
const sameWhen = (a: When, b: When) => (Object.keys(a) as (keyof When)[]).every((k) => a[k] === b[k]);

function Group({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-3">
      <legend className="mb-1 text-small font-semibold">{legend}</legend>
      {children}
    </fieldset>
  );
}

export function ScheduleForm({ schedule, form, activeNumber, onDone, onDelete }: {
  schedule: Schedule | null; form: StartForm; activeNumber: number; onDone: (saved?: Schedule) => void; onDelete?: () => void;
}) {  // prettier-ignore
  const t = useTriggers();
  const id = useId();
  const editing = schedule !== null;
  const [opened] = useState<When>(() => (schedule ? whenOf(schedule) : blankWhen("daily"))); // the When it opened with
  const [when, setWhen] = useState<When>(opened);
  const [zone, setZone] = useState(schedule?.time_zone ?? BROWSER_ZONE);
  const [mode, setMode] = useState<"live" | "simulate">(schedule?.mode ?? "live");
  const [catchup, setCatchup] = useState(schedule?.catchup_window_s ?? 600);
  const [replacing, setReplacing] = useState(!editing);
  const [values, setValues] = useState<ReadonlyMap<string, string>>(() => (editing ? new Map() : startValues(form)));
  const picks = usePicks();
  // A name comes from the version a schedule starts: another one shown since drops the picks (§5.5, as a run form's
  // re-read does).
  const [pickedFor, setPickedFor] = useState(form.version_id);
  if (pickedFor !== form.version_id) {
    setPickedFor(form.version_id);
    picks.clear();
  }
  const version = useQuery(versionQuery(t.tenantId, t.workflowId, form.version_id));
  const resolving = version.isPending; // the version's input decides how it's entered: nothing is taken before
  const whole = version.data !== undefined && !fieldsShow(inputOf(asGraph(version.data.graph)));
  const [asJson, setAsJson] = useState(false); // the whole input as JSON, chosen here
  const json = whole || asJson;
  const [jsonText, setJsonText] = useState<string | null>(null); // until typed, the fields' values
  const seeded = () => {
    const made = fromFields(form, values, false);
    return "input" in made && Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "";
  };
  const shownJson = jsonText ?? seeded();
  /** What's in the fields, as JSON; a field whose value doesn't read keeps the form where it is, saying why. */
  const toJson = () => {
    const made = fromFields(form, values, false);
    if ("problems" in made) return setErrors(made.problems);
    setErrors({});
    setJsonText(Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "");
    setAsJson(true);
  };
  /** What's in the JSON, in the fields; JSON no field shows as written stays JSON, saying why. */
  const toFields = () => {
    const read = wholeOf(shownJson);
    if ("problem" in read) return setErrors({ input: read.problem });
    const byName = new Map(form.fields.map((f) => [f.name, f]));
    const shown = new Map<string, string>();
    const left: string[] = [];
    for (const [k, v] of Object.entries(read.value)) {
      const f = byName.get(k);
      const s = f ? shownOf(f, v) : null;
      if (s === null) left.push(k);
      else shown.set(k, s);
    }
    if (left.length > 0) return setErrors({ input: `No field here shows ${listed(left)} as written: it stays as JSON.` });
    setErrors({});
    setValues(shown);
    setJsonText(null);
    setAsJson(false);
  };
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  // Its timing is sent only when changed here: one the form reads but wouldn't write the same stays as it is.
  const keep = editing && (when.preset === "kept" || sameWhen(when, opened));
  const cron = when.preset === "kept" ? schedule?.cron != null : when.preset === "daily" || when.preset === "weekdays" || when.preset === "custom";
  const presets = opened.preset === "kept" && schedule ? [{ value: "kept" as const, label: `${scheduleTitle(schedule)}, as it is` }, ...PRESETS] : PRESETS;
  const offered = zones();
  const set = (patch: Partial<When>) => setWhen((w) => ({ ...w, ...patch }));

  const save = useMutation({
    mutationFn: async () => {
      setErrors({});
      setRefused(null);
      const made = keep ? null : timingOf(when);
      if (made && "problem" in made) throw new Local({ [made.field]: made.problem });
      let input: Record<string, unknown> = {};
      if (replacing && json) {
        const read = wholeOf(shownJson);
        if ("problem" in read) throw new Local({ input: read.problem });
        input = read.value; // as parsed: never copied key by key, which would drop `__proto__`
      } else if (replacing) {
        const made = fromFields(form, values, true);
        if ("problems" in made) throw new Local(made.problems);
        input = made.input;
      }
      const names = replacing ? namesFor(picks.picks, input) : undefined;
      const timing = made?.timing ?? null;
      const time_zone = (timing ? timing.cron !== null : schedule?.cron != null) ? zone.trim() : "UTC";
      if (!editing) {
        if (!timing) throw new Local({ when: TIMING_WORDS.timing_missing! });
        return createSchedule(t.tenantId, t.workflowId, { ...timing, time_zone, catchup_window_s: catchup, mode, input, ...(names ? { names } : {}) });
      }
      const changed = (k: keyof Schedule, v: unknown) => schedule[k] !== v;
      return updateSchedule(t.tenantId, schedule.id, {
        ...(timing && (changed("cron", timing.cron) || changed("every_s", timing.every_s) || changed("offset_s", timing.offset_s)) ? timing : {}),
        // A zone is a cron's: an interval counts in UTC, so its edit never sends one (4c-3b's final review).
        ...((timing ? timing.cron !== null : schedule.cron !== null) && changed("time_zone", time_zone) ? { time_zone } : {}),
        ...(changed("catchup_window_s", catchup) ? { catchup_window_s: catchup } : {}),
        ...(changed("mode", mode) ? { mode } : {}),
        ...(replacing ? { input, ...(names ? { names } : {}) } : {}),
      });
    },
    onSuccess: (saved) => {
      announce(editing ? `Saved ${scheduleTitle(saved)}` : `Added the schedule ${scheduleTitle(saved)}`);
      onDone(saved);
    },
    onError: (e) => {
      if (e instanceof Local) return setErrors(e.fields);
      if (e instanceof ApiError && e.code === "schedule_invalid") {
        const problems = (e.body as { problems?: { field: string; code: string }[] }).problems ?? [];
        return setErrors(Object.fromEntries(problems.map((p) => [fieldOfProblem(p.field, when.preset), TIMING_WORDS[p.code] ?? "The scheduler can't take this."])));
      }
      if (e instanceof ApiError && e.code === "input_invalid") {
        const messages = (e.body as { messages?: string[] }).messages ?? [];
        return setRefused(`Version ${activeNumber}'s input refuses this: ${messages.join(" ") || "it doesn't fit."}`);
      }
      if (e instanceof ApiError && e.code === "csv_required") return setRefused("It takes a CSV file: its rows come from an upload, so it can't run on a schedule.");
      if (e instanceof ApiError && e.code === "not_active") return setRefused("Nothing is published any more: publish a version to schedule it.");
      setRefused(editing ? "The schedule couldn't be saved. Try again." : "The schedule couldn't be added. Try again.");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  const interval = intervalWords(when);
  return (
    <form
      onSubmit={submit} aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onDone();
        }
      }}
      className="flex flex-col gap-4 rounded-lg border border-line-strong p-3"
    >
      <h4 id={`${id}-title`} className="text-body font-semibold">{editing ? `Editing "${scheduleTitle(schedule)}"` : "New schedule"}</h4>
      <Select label="When" value={when.preset} error={errors.when} onChange={(e) => set({ preset: e.target.value as Preset })} autoFocus>
        {presets.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
      </Select>
      {when.preset === "kept" && <p className="text-small text-muted">Set outside this form, it&apos;s kept as it is: choosing another When replaces it.</p>}
      {(when.preset === "minutes" || when.preset === "hours") && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Every" inputMode="numeric" value={when.every} error={errors.every} onChange={(e) => set({ every: e.target.value })} />
          {when.preset === "minutes" ? (
            <Field label="Past the hour" inputMode="numeric" value={when.past} error={errors.past} onChange={(e) => set({ past: e.target.value })} />
          ) : (
            <Field label="First, in UTC" type="time" value={when.first} error={errors.first} onChange={(e) => set({ first: e.target.value })} />
          )}
        </div>
      )}
      {interval && <p className="text-small text-muted">{interval}</p>}
      {(when.preset === "daily" || when.preset === "weekdays") && (
        <Field
          label="Time" type="time" value={when.time} error={errors.time}
          hint={editing && schedule.cron ? `Its cron, ${schedule.cron}, read back as a preset. A cron no preset says opens as Custom.` : undefined}
          onChange={(e) => set({ time: e.target.value })}
        />
      )}
      {when.preset === "custom" && (
        <Field
          label="Cron" value={when.cron} spellCheck={false} autoCapitalize="off" error={errors.cron}
          hint="Five fields: minute, hour, day of the month, month, day of the week (0 or 7 is Sunday). Ranges, lists and steps work, like 1-5, 1,15 or */10, and names like MON or JAN."
          onChange={(e) => set({ cron: e.target.value })}
        />
      )}
      {cron && (
        <>
          <Field
            label="Time zone" list={`${id}-zones`} value={zone} error={errors.zone} spellCheck={false} autoCapitalize="off"
            hint={editing ? 'Type to search the zones, like "york" or "UTC".' : "Your browser's zone to start with. Each schedule keeps its own."}
            onChange={(e) => setZone(e.target.value)}
          />
          <datalist id={`${id}-zones`}>{offered.map((z) => <option key={z} value={z} />)}</datalist>
        </>
      )}
      <Group legend="Mode">
        {(["live", "simulate"] as const).map((m) => (
          <label key={m} className="flex min-h-6 items-center gap-2 text-small">
            <input type="radio" name={`${id}-mode`} checked={mode === m} onChange={() => setMode(m)} className="size-[16px] accent-accent" />
            {m === "live" ? "Live" : "Simulate"}
          </label>
        ))}
        <p className="text-small text-muted">Simulate: steps that change other systems send nothing.</p>
      </Group>
      <Select label="If a firing is missed, still start it within" value={String(catchup)} error={errors.catchup} onChange={(e) => setCatchup(Number(e.target.value))}>
        {CATCHUP.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        {!CATCHUP.some((c) => c.value === catchup) && <option value={catchup}>{catchup} seconds</option>}
      </Select>
      <Group legend={replacing ? (editing ? `Input · replacing it with version ${activeNumber}'s form` : `Input · version ${activeNumber}'s form`) : "Input"}>
        {!replacing ? (
          <>
            <p className="text-small text-muted">Set when it was created; not shown back.</p>
            <Button size="sm" className="self-start" onClick={() => setReplacing(true)}>Replace the input…</Button>
          </>
        ) : (
          <>
            {resolving ? (
              <p className="text-small text-muted">Loading version {activeNumber}&apos;s input…</p>
            ) : json ? (
              <>
                {whole && <p className="text-small text-muted">Version {activeNumber}&apos;s input has rules this form can&apos;t show field by field: it&apos;s entered as JSON.</p>}
                <TextArea
                  label="The input, as JSON" hint='An object, like {"site": "HQ"}. Shown as typed, a sensitive value too.' error={errors.input}
                  value={shownJson} rows={6} spellCheck={false} onChange={(e) => setJsonText(e.target.value)}
                />
                {!whole && <Button size="sm" className="self-start" onClick={toFields}>Enter it field by field</Button>}
              </>
            ) : (
              <PickerProvider
                value={{
                  tenantId: t.tenantId, scope: JSON.stringify([t.tenantId, t.workflowId, form.version_id]),
                  read: versionChoices(t.tenantId, t.workflowId, form.version_id), draft: false, simulated: mode === "simulate", picks: picks.picks, onPick: picks.onPick,
                }}
              >
                {version.isError && <p className="text-small text-muted">Version {activeNumber}&apos;s input couldn&apos;t be loaded: its fields are shown, and Enter it as JSON takes any rule they don&apos;t.</p>}
                {form.fields.length === 0 && <p className="text-small text-muted">Version {activeNumber} takes no input.</p>}
                {form.fields.map((f) => (
                  <InputControl
                    key={f.name} f={f} value={values.get(f.name)} error={errors[fieldKey(f.name)]}
                    onChange={(v) => setValues((m) => new Map(m).set(f.name, v))}
                  />
                ))}
                <Button size="sm" className="self-start" onClick={toJson}>Enter it as JSON</Button>
              </PickerProvider>
            )}
            <p className="text-small text-muted">
              {editing
                ? "The stored input isn't shown back: what you enter here replaces it whole."
                : "Kept with the schedule and checked against the published version's input each time it fires. It isn't shown back afterwards."}
            </p>
            {editing && <Button size="sm" className="self-start" onClick={() => setReplacing(false)}>Keep the stored input</Button>}
          </>
        )}
      </Group>
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={save.isPending || (replacing && resolving)}>{editing ? "Save" : "Add the schedule"}</Button>
        <Button size="sm" onClick={() => onDone()}>Cancel</Button>
        {editing && onDelete && <Button size="sm" variant="danger-outline" onClick={onDelete}>Delete the schedule…</Button>}
      </div>
      {editing && (
        <p className="text-small text-muted">
          Saved at once: the mode and input apply from its next firing. The scheduler takes a new time on its own; until that&apos;s confirmed, the previous time may still fire.
        </p>
      )}
    </form>
  );  // prettier-ignore
}

/** What the browser finds before anything is sent, by field. */
class Local extends Error {
  constructor(public fields: Record<string, string>) {
    super("not sent");
  }
}
