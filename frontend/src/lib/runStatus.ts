// SPDX-License-Identifier: Apache-2.0
// A run's status in words (editor 4e-1; the runs design §5.5): one vocabulary for the Runs page, a run's page, the
// Workflows list and the Simulation panel. Each status has its word and its look; the look only repeats the word. And
// what a run's facts read as everywhere: its name, how long it ran, why it didn't start.
import type { Schemas } from "./client";

export type RunStatus = Schemas["RunItemOut"]["status"];

/** How a status looks: dashed and neutral while it waits, the accent while it runs, ok, danger, or neutral. */
export type Tone = "waiting" | "running" | "ok" | "danger" | "neutral";

export const RUN_STATUS: Record<RunStatus, { word: string; tone: Tone }> = {
  queued: { word: "Queued", tone: "waiting" },
  starting: { word: "Starting", tone: "waiting" },
  running: { word: "Running", tone: "running" },
  succeeded: { word: "Succeeded", tone: "ok" },
  failed: { word: "Failed", tone: "danger" },
  deadline_exceeded: { word: "Ran out of time", tone: "danger" },
  cancelled: { word: "Cancelled", tone: "neutral" },
  dead: { word: "Couldn't start", tone: "danger" },
  refused: { word: "Refused", tone: "danger" },
};

/** How long a run ran, as a person reads it: "14 s", "3 min 20 s", "1 h 2 min"; null when either end is unknown. */
export function duration(from: string | null, to: string | null): string | null {
  if (from === null || to === null) return null;
  const s = Math.round((Date.parse(to) - Date.parse(from)) / 1000);
  if (s < 1) return "under 1 s";
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
  return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ""}`;
}

/** A run named by its id's first eight characters (a run's id is its request's). */
export const runId = (id: string) => id.slice(0, 8);

// Why a request never started (admission's refusals, the dispatcher's dead starts): the request keeps only its code
// (4e-1a ruling 4), so the code is worded here. A code from a later server has no words: its code is shown alone.
const REASONS: Record<string, string> = {
  input_invalid: "Its input didn't fit the workflow's input.",
  tenant_erasing: "The tenant is being erased: it starts no run.",
  production_runs_disabled: "Production runs are off in this deployment.",
  environment_not_recorded: "This deployment's environment isn't recorded, so it starts no live run.",
  workflow_disabled: "The workflow is disabled.",
  not_active: "The workflow has no published version.",
  no_current_build: "No current build was recorded, so its version couldn't be checked.",
  version_unusable: "Its version can't run on the current build.",
  node_type_retired: "A step type it uses has been retired.",
  cel_profile_retired: "The formula profile it was checked against has been retired.",
  csv_not_declared: "The workflow takes no CSV file.",
  csv_mapping_invalid: "The CSV file's columns didn't map to the workflow's.",
  upload_not_found: "Its CSV upload wasn't found.",
  upload_expired: "Its CSV upload had expired.",
  upload_consumed: "Its CSV upload had already started a run.",
  target_invalid: "The step it tested can't run alone.",
  csv_not_simulated: "A CSV file can't be simulated yet.",
  schedule_paused: "Its schedule was disabled.",
  schedule_deleted: "Its schedule was deleted.",
  schedule_catchup_expired: "Its tick was past its schedule's catch-up window.",
  envelope_unreadable: "Its input couldn't be opened to start it.",
  id_collision: "Another run held its id.",
  start_check_unavailable: "Its start couldn't be checked: an infrastructure failure.",
  start_throttled: "Too many runs were starting at once.",
  start_refused: "Its start was refused.",
  start_abandoned: "An operator ended it before it started.",
};

/** Why a request didn't start, in words; null for no code, or one these words don't know. */
export const reasonWords = (code: string | null): string | null => (code === null ? null : (REASONS[code] ?? null));
